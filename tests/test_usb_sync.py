import logging
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import nextcloud_sync
import usb_sync
from tests.helpers import folder_name, make_tree, read_tree

FA, FB, FC, FD, FE = (folder_name(month) for month in range(1, 6))
VIDEO = {'v.mp4': 'video'}


class UsbSyncTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        for patcher in (mock.patch('time.sleep'), mock.patch('os.chown'),
                        mock.patch('console.CONSOLE_PATH', str(self.base / 'tty')),
                        mock.patch('nextcloud_sync.NEXTCLOUD_CONFIG_FILE', str(self.base / 'nextcloud.conf'))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def setup_drives(self, usb, local):
        self.usb, self.local = self.base / 'usb', self.base / 'local'
        make_tree(self.usb, usb)
        make_tree(self.local, local)
        return usb_sync.USBSync(str(self.local))


class Planning(UsbSyncTestCase):
    def test_redated_folders_are_renamed_not_deleted(self):
        sync = self.setup_drives({FC: VIDEO, FD: VIDEO}, {FA: VIDEO, FB: VIDEO})
        self.assertEqual(sync.plan_sync(self.usb),
                         {'update': [], 'copy': [], 'rename': [(FA, FC), (FB, FD)], 'delete': []})

    def test_folder_still_on_the_drive_is_never_renamed(self):
        sync = self.setup_drives({FA: VIDEO, FB: VIDEO, FC: VIDEO}, {FA: VIDEO, FB: VIDEO})
        self.assertEqual(sync.plan_sync(self.usb),
                         {'update': [FA, FB], 'copy': [FC], 'rename': [], 'delete': []})

    def test_mixed_case(self):
        sync = self.setup_drives(
            {FA: {'a.mp4': 'new'}, FB: {'b.mp4': 'b'}, FC: {'c.mp4': 'c'}},
            {FA: {'a.mp4': 'old!'}, FD: {'b.mp4': 'b'}, FE: {'z.mp4': 'z'}})
        self.assertEqual(sync.plan_sync(self.usb),
                         {'update': [FA], 'copy': [FC], 'rename': [(FD, FB)], 'delete': [FE]})

    def test_planning_changes_nothing(self):
        sync = self.setup_drives({FB: VIDEO}, {FA: VIDEO, FC: {'other.mp4': 'x'}})
        before = read_tree(self.local)
        sync.plan_sync(self.usb)
        self.assertEqual(read_tree(self.local), before)

    def test_first_drive_with_folders_is_the_source(self):
        sync = self.setup_drives({FA: VIDEO}, {})
        empty = self.base / 'empty'
        empty.mkdir()
        self.assertEqual(sync.find_sync_source([empty, self.usb]), self.usb)
        self.assertIsNone(sync.find_sync_source([empty]))


class ScheduleNames(UsbSyncTestCase):
    SEVERAL = '2026-01-01_to_2026-01-02_0500_to_0900_and_1600_to_2300'
    BAD = '2026-01-01_to_2026-01-02_0500_to_0900_and_1600'

    def test_several_windows_are_synced(self):
        sync = self.setup_drives({self.SEVERAL: VIDEO}, {})
        self.assertTrue(sync.sync_usb_to_local(self.usb))
        self.assertEqual(sorted(read_tree(self.local)), [self.SEVERAL])

    def test_bad_name_is_not_copied(self):
        sync = self.setup_drives({self.BAD: VIDEO, FA: VIDEO}, {})
        self.assertEqual(sync.plan_sync(self.usb)['copy'], [FA])

    def test_bad_local_name_is_left_alone(self):
        sync = self.setup_drives({FA: VIDEO}, {self.BAD: {'other.mp4': 'x'}})
        self.assertEqual(sync.plan_sync(self.usb), {'update': [], 'copy': [FA], 'rename': [], 'delete': []})

    def test_two_folders_can_become_one(self):
        """Replacing two single-window folders with one that has both windows"""
        sync = self.setup_drives({self.SEVERAL: VIDEO}, {FA: VIDEO, FB: VIDEO})
        self.assertEqual(sync.plan_sync(self.usb),
                         {'update': [], 'copy': [], 'rename': [(FA, self.SEVERAL)], 'delete': [FB]})
        self.assertTrue(sync.sync_usb_to_local(self.usb))
        self.assertEqual(sorted(read_tree(self.local)), [self.SEVERAL])


class Syncing(UsbSyncTestCase):
    def test_redate(self):
        sync = self.setup_drives({FC: VIDEO, FD: VIDEO}, {FA: VIDEO, FB: VIDEO})
        self.assertTrue(sync.sync_usb_to_local(self.usb))
        self.assertEqual(sorted(read_tree(self.local)), [FC, FD])

    def test_rename_avoids_copying(self):
        sync = self.setup_drives({FB: VIDEO}, {FA: VIDEO})
        with mock.patch.object(usb_sync.shutil, 'copy2') as copy:
            os.utime(self.local / FA / 'v.mp4', (2000, 2000))
            os.utime(self.usb / FB / 'v.mp4', (1000, 1000))
            self.assertTrue(sync.sync_usb_to_local(self.usb))
        copy.assert_not_called()

    def test_third_folder_with_same_video_keeps_the_others(self):
        sync = self.setup_drives({FA: VIDEO, FB: VIDEO, FC: VIDEO}, {FA: VIDEO, FB: VIDEO})
        self.assertTrue(sync.sync_usb_to_local(self.usb))
        self.assertEqual(sorted(read_tree(self.local)), [FA, FB, FC])

    def test_mixed_case_result_matches_plan(self):
        sync = self.setup_drives(
            {FA: {'a.mp4': 'new'}, FB: {'b.mp4': 'b'}, FC: {'c.mp4': 'c'}},
            {FA: {'a.mp4': 'old!'}, FD: {'b.mp4': 'b'}, FE: {'z.mp4': 'z'}})
        self.assertTrue(sync.sync_usb_to_local(self.usb))
        result = read_tree(self.local)
        self.assertEqual(sorted(result), [FA, FB, FC])
        self.assertEqual(result[FA]['a.mp4'], 'new')

    def test_empty_drive_touches_nothing(self):
        sync = self.setup_drives({}, {FA: VIDEO})
        self.assertFalse(sync.sync_usb_to_local(self.usb))
        self.assertEqual(sorted(read_tree(self.local)), [FA])

    def test_failed_copy_keeps_old_video_and_old_folders(self):
        sync = self.setup_drives({FA: {'a.mp4': 'NEW-VERSION'}, FB: {'b.mp4': 'b'}},
                                 {FA: {'a.mp4': 'old', 'gone.mp4': 'still here'}, FC: {'old.mp4': 'keep me'}})
        real_copy = shutil.copy2

        def interrupted(source, destination, **kwargs):
            if Path(source).name == 'a.mp4':
                Path(destination).write_text('NEW-')
                raise OSError(28, 'No space left on device')
            return real_copy(source, destination, **kwargs)

        with mock.patch.object(usb_sync.shutil, 'copy2', interrupted), \
                self.assertLogs('usb_sync', logging.WARNING) as logs:
            self.assertFalse(sync.sync_usb_to_local(self.usb))
        result = read_tree(self.local)
        self.assertEqual(result[FA], {'a.mp4': 'old', 'gone.mp4': 'still here'})
        self.assertIn(FC, result)
        output = '\n'.join(logs.output)
        self.assertIn('No space left', output)
        self.assertIn('Keeping old folders', output)


class OnBoot(UsbSyncTestCase):
    def test_syncs_from_the_first_drive_with_folders(self):
        sync = self.setup_drives({FA: VIDEO}, {})
        with mock.patch.object(sync, 'find_usb_drives', return_value=[self.usb]):
            self.assertTrue(sync.sync_on_boot())
        self.assertEqual(sorted(read_tree(self.local)), [FA])

    def test_nothing_to_do_without_a_drive(self):
        sync = self.setup_drives({}, {FA: VIDEO})
        with mock.patch.object(sync, 'find_usb_drives', return_value=[]):
            self.assertFalse(sync.sync_on_boot())
        self.assertEqual(sorted(read_tree(self.local)), [FA])

    def test_nextcloud_turns_usb_video_sync_off(self):
        sync = self.setup_drives({FA: VIDEO}, {FB: VIDEO})
        nextcloud_sync.save_config(nextcloud_sync.make_config({'share_url': 'https://cloud.test/s/abc'}))
        with mock.patch.object(sync, 'find_usb_drives', return_value=[self.usb]):
            self.assertFalse(sync.sync_on_boot())
        self.assertEqual(sorted(read_tree(self.local)), [FB])
        self.assertIn('Nextcloud sync is on', (self.base / 'tty').read_text())

    def test_turned_off_nextcloud_leaves_usb_sync_on(self):
        sync = self.setup_drives({FA: VIDEO}, {})
        nextcloud_sync.save_config(nextcloud_sync.make_config({'share_url': 'https://cloud.test/s/abc', 'enabled': False}))
        with mock.patch.object(sync, 'find_usb_drives', return_value=[self.usb]):
            self.assertTrue(sync.sync_on_boot())
        self.assertEqual(sorted(read_tree(self.local)), [FA])

    def test_nextcloud_txt_is_imported_and_takes_over(self):
        sync = self.setup_drives({FA: VIDEO}, {FB: VIDEO})
        (self.usb / 'nextcloud.txt').write_text('share_url=https://cloud.test/s/abc\n')
        with mock.patch.object(sync, 'find_usb_drives', return_value=[self.usb]):
            self.assertFalse(sync.sync_on_boot())
        self.assertTrue(nextcloud_sync.is_enabled())
        self.assertEqual(sorted(read_tree(self.local)), [FB])

    def test_bad_nextcloud_txt_is_explained_and_usb_sync_continues(self):
        sync = self.setup_drives({FA: VIDEO}, {})
        (self.usb / 'nextcloud.txt').write_text('share_url=not a link\n')
        shown = []
        real = sync.display_message_on_screen
        sync.display_message_on_screen = lambda m: (shown.append(m), real(m))
        with mock.patch.object(sync, 'find_usb_drives', return_value=[self.usb]):
            self.assertTrue(sync.sync_on_boot())
        self.assertIn('Problem in nextcloud.txt', shown[0])
        self.assertFalse(nextcloud_sync.is_enabled())

    def test_time_file_on_the_drive_is_just_ignored(self):
        sync = self.setup_drives({FA: VIDEO}, {})
        (self.usb / 'rtc_time.txt').write_text('2020-01-01 00:00:00')
        with mock.patch.object(sync, 'find_usb_drives', return_value=[self.usb]):
            self.assertTrue(sync.sync_on_boot())
        self.assertFalse(hasattr(sync, 'check_rtc_time_file'))


class SyncFolder(UsbSyncTestCase):
    def test_leftover_temp_file_is_ignored_then_removed(self):
        sync = self.setup_drives({FA: {'a.mp4': 'new'}}, {FA: {'a.mp4': 'old', '.a.mp4.tmp': 'partial'}})
        self.assertNotIn('.a.mp4.tmp', sync.get_folder_files_dict(self.local / FA))
        sync.sync_folder(self.usb / FA, self.local / FA)
        self.assertEqual([p.name for p in (self.local / FA).iterdir()], ['a.mp4'])

    def test_copies_updates_and_mirrors(self):
        sync = self.setup_drives(
            {FA: {'a.mp4': 'a', 'projector.txt': 'p2'}},
            {FA: {'old.mp4': 'x', 'projector.conf': 'c', 'notes.txt': 'n', 'projector.txt': 'p1!'}})
        self.assertEqual(sync.sync_folder(self.usb / FA, self.local / FA), (1, 1, []))
        self.assertEqual(read_tree(self.local)[FA],
                         {'a.mp4': 'a', 'projector.txt': 'p2', 'notes.txt': 'n'})

    def test_unchanged_file_is_not_copied(self):
        sync = self.setup_drives({FA: {'a.mp4': 'same'}}, {FA: {'a.mp4': 'same'}})
        os.utime(self.usb / FA / 'a.mp4', (1000, 1000))
        os.utime(self.local / FA / 'a.mp4', (2000, 2000))
        self.assertEqual(sync.sync_folder(self.usb / FA, self.local / FA), (0, 0, []))

    def test_copied_file_is_given_to_looper_before_it_appears(self):
        sync = self.setup_drives({FA: {'a.mp4': 'a'}}, {FA: {}})
        sync.sync_folder(self.usb / FA, self.local / FA)
        chowned = [Path(call.args[0]).name for call in os.chown.call_args_list]
        self.assertEqual(chowned, ['.a.mp4.tmp'])
