import os
import sys
import show.main as show
from click.testing import CliRunner
from unittest import mock
from unittest.mock import call

test_path = os.path.dirname(os.path.abspath(__file__))
modules_path = os.path.dirname(test_path)
sys.path.insert(0, test_path)
sys.path.insert(0, modules_path)

class TestShowRunAllCommands(object):
    @classmethod
    def setup_class(cls):
        print("SETUP")
        os.environ["UTILITIES_UNIT_TESTING"] = "1"

    def test_show_runningconfiguration_all(self):
        def run_command_side_effect(*args, **kwargs):
            return "{}"
        with mock.patch('show.main.run_command',
                mock.MagicMock(side_effect=run_command_side_effect)) as mock_run_command:
            result = CliRunner().invoke(show.cli.commands['runningconfiguration'].commands['all'], [])
        assert mock_run_command.call_count == 2
        assert mock_run_command.call_args_list == [
            call('sonic-cfggen -d --print-data', display_cmd=False, return_cmd=True),
            call("sudo rvtysh -c 'show running-config'", display_cmd=False, return_cmd=True)]

    @classmethod
    def teardown_class(cls):
        print("TEARDOWN")
        os.environ["PATH"] = os.pathsep.join(os.environ["PATH"].split(os.pathsep)[:-1])
        os.environ["UTILITIES_UNIT_TESTING"] = "0"
