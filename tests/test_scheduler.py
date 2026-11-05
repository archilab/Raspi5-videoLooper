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
            'windows': [(time(9, 0), time(18, 0))],
        })

    def test_several_windows(self):
        schedule = scheduler.parse_folder_name('2026-11-01_to_2026-11-30_0500_to_0900_and_1600_to_2300_and_2330_to_0100')
        self.assertEqual(schedule['windows'], [(time(5, 0), time(9, 0)), (time(16, 0), time(23, 0)),
                                               (time(23, 30), time(1, 0))])

    def test_invalid_names(self):
        for name in ('videos', '2026-11-01_to_2026-11-30', '2026-13-01_to_2026-11-30_0900_to_1800',
                     '2026-11-01_to_2026-02-30_0900_to_1800', '2026-11-01_to_2026-11-30_2500_to_1800',
                     '.hidden', '',
                     '2026-11-01_to_2026-11-30_0900_to_1800_backup',
                     '2026-11-01_to_2026-11-30_0900_to_1800_and',
                     '2026-11-01_to_2026-11-30_0900_to_1800_and_1600',
                     '2026-11-01_to_2026-11-30_0900_to_1800_1600_to_2300',
                     '2026-11-01_to_2026-11-30_0900_to_1800_and_2500_to_2600',
                     'x2026-11-01_to_2026-11-30_0900_to_1800'):
            self.assertIsNone(scheduler.parse_folder_name(name), name)

    def test_warns_once_about_a_mistyped_schedule(self):
        name = '2026-11-01_to_2026-11-30_0900_to_1800_and_1600'
        scheduler._warned_names.discard(name)
        with self.assertLogs('scheduler', 'WARNING') as logs:
            scheduler.parse_folder_name(name)
            scheduler.parse_folder_name(name)
        self.assertEqual(len(logs.output), 1)
        self.assertIn(name, logs.output[0])

    def test_no_warning_for_other_folders(self):
        with self.assertNoLogs('scheduler', 'WARNING'):
            scheduler.parse_folder_name('holiday pictures')


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


class SeveralWindows(unittest.TestCase):
    TWO = '2026-11-01_to_2026-11-30_0500_to_0900_and_1600_to_2300'
    THREE = '2026-11-01_to_2026-11-30_0700_to_0900_and_1200_to_1400_and_1800_to_2200'

    def check(self, expected, name, *moment):
        self.assertEqual(scheduler.is_folder_active(name, datetime(*moment)), expected, moment)

    def test_inside_each_window(self):
        self.check(True, self.TWO, 2026, 11, 5, 7, 0)
        self.check(True, self.TWO, 2026, 11, 5, 20, 0)
        for hour in (8, 13, 20):
            self.check(True, self.THREE, 2026, 11, 5, hour, 0)

    def test_gaps_are_outside(self):
        self.check(False, self.TWO, 2026, 11, 5, 4, 59)
        self.check(False, self.TWO, 2026, 11, 5, 12, 0)
        self.check(False, self.TWO, 2026, 11, 5, 23, 1)
        for hour in (6, 10, 15, 23):
            self.check(False, self.THREE, 2026, 11, 5, hour, 0)

    def test_edges_of_every_window(self):
        for hour, minute in ((5, 0), (9, 0), (16, 0), (23, 0)):
            self.check(True, self.TWO, 2026, 11, 5, hour, minute)
        self.check(False, self.TWO, 2026, 11, 5, 9, 1)
        self.check(False, self.TWO, 2026, 11, 5, 15, 59)

    def test_outside_the_dates(self):
        self.check(False, self.TWO, 2026, 10, 31, 7, 0)
        self.check(False, self.TWO, 2026, 12, 1, 20, 0)

    def test_touching_windows_have_no_gap(self):
        name = '2026-11-01_to_2026-11-30_0900_to_1200_and_1200_to_1500'
        for hour in (9, 11, 12, 13, 15):
            self.check(True, name, 2026, 11, 5, hour, 0)

    def test_overnight_window_in_a_list(self):
        name = '2026-11-01_to_2026-11-03_0600_to_0900_and_2200_to_0200'
        self.check(True, name, 2026, 11, 3, 7, 0)
        self.check(True, name, 2026, 11, 3, 23, 0)
        self.check(True, name, 2026, 11, 4, 1, 0)
        self.check(False, name, 2026, 11, 4, 7, 0)
        self.check(False, name, 2026, 11, 1, 1, 0)

    def test_order_of_windows_does_not_matter(self):
        name = '2026-11-01_to_2026-11-30_1600_to_2300_and_0500_to_0900'
        self.check(True, name, 2026, 11, 5, 7, 0)
        self.check(True, name, 2026, 11, 5, 20, 0)

    def test_found_as_the_active_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            videos = Path(tmp) / 'videos'
            make_tree(videos, {self.TWO: {'a.mp4': ''}})
            self.assertEqual(scheduler.find_active_folder(videos, datetime(2026, 11, 5, 20, 0))[0].name, self.TWO)
            self.assertIsNone(scheduler.find_active_folder(videos, datetime(2026, 11, 5, 12, 0)))

    def test_latest_start_date_still_wins(self):
        newer = '2026-11-02_to_2026-11-30_0600_to_0800_and_1900_to_2100'
        with tempfile.TemporaryDirectory() as tmp:
            videos = Path(tmp) / 'videos'
            make_tree(videos, {self.TWO: {'a.mp4': ''}, newer: {'b.mp4': ''}})
            self.assertEqual(scheduler.find_active_folder(videos, datetime(2026, 11, 5, 20, 0))[0].name, newer)
            self.assertEqual(scheduler.find_active_folder(videos, datetime(2026, 11, 5, 17, 0))[0].name, self.TWO)


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
