import tempfile
import unittest
from datetime import date, datetime, time
from pathlib import Path

import scheduler
from tests.helpers import make_tree

NOVEMBER = '2026-11-01_to_2026-11-30_0900_to_1800'


class ParseFolderName(unittest.TestCase):
    def test_valid_name(self):
        self.assertEqual(scheduler.parse_folder_name(NOVEMBER), {
            'start_date': date(2026, 11, 1), 'end_date': date(2026, 11, 30),
            'start_time': time(9, 0), 'end_time': time(18, 0),
        })

    def test_invalid_names(self):
        for name in ('videos', '2026-11-01_to_2026-11-30', '2026-13-01_to_2026-11-30_0900_to_1800',
                     '2026-11-01_to_2026-02-30_0900_to_1800', '2026-11-01_to_2026-11-30_2500_to_1800',
                     '.hidden', ''):
            self.assertIsNone(scheduler.parse_folder_name(name), name)


class IsFolderActive(unittest.TestCase):
    def check(self, expected, *moment, name=NOVEMBER):
        self.assertEqual(scheduler.is_folder_active(name, datetime(*moment)), expected, moment)

    def test_inside_dates_and_hours(self):
        self.check(True, 2026, 11, 5, 12, 0)

    def test_outside_dates(self):
        self.check(False, 2026, 10, 31, 12, 0)
        self.check(False, 2026, 12, 1, 12, 0)

    def test_outside_hours(self):
        self.check(False, 2026, 11, 5, 8, 59)
        self.check(False, 2026, 11, 5, 18, 1)

    def test_edges_are_included(self):
        self.check(True, 2026, 11, 1, 9, 0)
        self.check(True, 2026, 11, 30, 18, 0)

    def test_invalid_name_is_never_active(self):
        self.check(False, 2026, 11, 5, 12, 0, name='videos')


class Overnight(unittest.TestCase):
    NIGHT = '2026-11-01_to_2026-11-03_2200_to_0600'

    def check(self, expected, *moment):
        self.assertEqual(scheduler.is_folder_active(self.NIGHT, datetime(*moment)), expected, moment)

    def test_before_and_after_midnight(self):
        self.check(True, 2026, 11, 2, 23, 0)
        self.check(True, 2026, 11, 3, 3, 0)

    def test_daytime_is_outside(self):
        self.check(False, 2026, 11, 2, 12, 0)
        self.check(False, 2026, 11, 2, 21, 59)
        self.check(False, 2026, 11, 2, 6, 1)

    def test_edges(self):
        self.check(True, 2026, 11, 1, 22, 0)
        self.check(True, 2026, 11, 2, 6, 0)

    def test_first_night_starts_in_the_evening(self):
        self.check(False, 2026, 11, 1, 3, 0)

    def test_last_night_runs_past_the_end_date(self):
        self.check(True, 2026, 11, 3, 23, 0)
        self.check(True, 2026, 11, 4, 5, 59)
        self.check(False, 2026, 11, 4, 6, 1)
        self.check(False, 2026, 11, 4, 23, 0)

    def test_crosses_month_and_year_ends(self):
        new_year = '2026-12-31_to_2026-12-31_2200_to_0200'
        self.assertTrue(scheduler.is_folder_active(new_year, datetime(2027, 1, 1, 1, 0)))
        self.assertFalse(scheduler.is_folder_active(new_year, datetime(2027, 1, 1, 3, 0)))

    def test_equal_times_are_not_overnight(self):
        name = '2026-11-01_to_2026-11-03_0900_to_0900'
        self.assertTrue(scheduler.is_folder_active(name, datetime(2026, 11, 2, 9, 0)))
        self.assertFalse(scheduler.is_folder_active(name, datetime(2026, 11, 2, 10, 0)))

    def test_found_as_the_active_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            videos = Path(tmp) / 'videos'
            make_tree(videos, {self.NIGHT: {'a.mp4': ''}})
            found = scheduler.find_active_folder(videos, datetime(2026, 11, 4, 2, 0))
            self.assertEqual(found[0].name, self.NIGHT)


class FindingFolders(unittest.TestCase):
    NOW = datetime(2026, 11, 5, 12, 0)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.videos = Path(tmp.name) / 'videos'

    def test_picks_the_active_folder(self):
        make_tree(self.videos, {NOVEMBER: {'a.mp4': ''}, '2026-12-01_to_2026-12-31_0900_to_1800': {'b.mp4': ''}})
        folder, files = scheduler.find_active_folder(self.videos, self.NOW)
        self.assertEqual(folder.name, NOVEMBER)
        self.assertEqual([f.name for f in files], ['a.mp4'])

    def test_latest_start_date_wins(self):
        newest = '2026-11-04_to_2026-11-30_0900_to_1800'
        make_tree(self.videos, {NOVEMBER: {'a.mp4': ''}, newest: {'b.mp4': ''},
                                '2026-10-01_to_2026-11-30_0900_to_1800': {'c.mp4': ''}})
        self.assertEqual(scheduler.find_active_folder(self.videos, self.NOW)[0].name, newest)

    def test_active_folder_needs_a_video(self):
        make_tree(self.videos, {NOVEMBER: {'notes.txt': '', '.hidden.mp4': ''}})
        self.assertIsNone(scheduler.find_active_folder(self.videos, self.NOW))

    def test_nothing_active(self):
        make_tree(self.videos, {'2026-12-01_to_2026-12-31_0900_to_1800': {'a.mp4': ''}})
        self.assertIsNone(scheduler.find_active_folder(self.videos, self.NOW))

    def test_missing_videos_folder(self):
        self.assertIsNone(scheduler.find_active_folder(self.videos, self.NOW))
        self.assertEqual(scheduler.get_all_valid_folders(self.videos), [])

    def test_video_files_are_filtered_and_sorted(self):
        make_tree(self.videos, {NOVEMBER: {'b.MP4': '', 'a.mkv': '', '.c.mp4': '', 'd.txt': '', 'projector.txt': ''}})
        files = scheduler.get_video_files(self.videos / NOVEMBER)
        self.assertEqual([f.name for f in files], ['a.mkv', 'b.MP4'])

    def test_all_valid_folders_are_chronological(self):
        december, october = '2026-12-01_to_2026-12-31_0900_to_1800', '2026-10-01_to_2026-10-31_0900_to_1800'
        make_tree(self.videos, {december: {'a.mp4': ''}, october: {'b.mp4': ''}, NOVEMBER: {'c.mp4': ''},
                                'not-a-schedule': {'d.mp4': ''}, '2026-01-01_to_2026-01-02_0900_to_1800': {'x.txt': ''}})
        names = [folder.name for folder, _ in scheduler.get_all_valid_folders(self.videos)]
        self.assertEqual(names, [october, NOVEMBER, december])
