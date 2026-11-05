import logging
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
                        mock.patch('console.CONSOLE_PATH', str(self.base / 'tty'))):
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
