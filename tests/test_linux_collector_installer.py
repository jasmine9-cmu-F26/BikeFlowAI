"""Offline dry-run checks for the Linux systemd/cron collector installer."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/data/install_divvy_collector.sh'


@unittest.skipIf(os.name=='nt' or not shutil.which('bash'),'Linux/macOS shell installer')
class LinuxInstallerTests(unittest.TestCase):
    def run_installer(self,*args):
        return subprocess.run(['bash',str(SCRIPT),'--python',sys.executable,*args],capture_output=True,text=True)

    def test_systemd_dry_run_is_oneshot_timer_without_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_home=Path(tmp)/'config'
            result=subprocess.run(['bash',str(SCRIPT),'--python',sys.executable,'--data-root',tmp,'--mode','systemd','--dry-run'],
                capture_output=True,text=True,env={**os.environ,'XDG_CONFIG_HOME':str(env_home)})
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('Type=oneshot',result.stdout);self.assertIn('OnCalendar=*:0/2:00',result.stdout)
            self.assertIn('--once --stop-at "2026-12-13T07:59:00+00:00"',result.stdout)
            self.assertFalse(env_home.exists());self.assertFalse((Path(tmp)/'current_validation').exists())

    def test_cron_dry_run_marks_entry_and_honours_interval(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=self.run_installer('--data-root',tmp,'--mode','cron','--interval-minutes','5','--dry-run')
            self.assertEqual(result.returncode,0,result.stderr)
            line=result.stdout.strip().splitlines()[-1]
            self.assertTrue(line.startswith('*/5 * * * * '));self.assertTrue(line.endswith('# bikeflowai-divvy-gbfs-collector'))

    def test_rejects_out_of_range_interval(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=self.run_installer('--data-root',tmp,'--mode','cron','--interval-minutes','7','--dry-run')
            self.assertEqual(result.returncode,2);self.assertIn('1-5 minute',result.stderr)

if __name__=='__main__':unittest.main()
