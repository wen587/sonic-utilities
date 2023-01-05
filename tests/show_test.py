import os
import sys
import show.main as show
from click.testing import CliRunner
from unittest import mock
from unittest.mock import call, MagicMock

test_path = os.path.dirname(os.path.abspath(__file__))
modules_path = os.path.dirname(test_path)
sys.path.insert(0, test_path)
sys.path.insert(0, modules_path)

class TestCommonFunc(object):
    @classmethod
    def setup_class(cls):
        print("SETUP")
        os.environ["UTILITIES_UNIT_TESTING"] = "1"

    def test_get_cmd_output(self):
        with mock.patch('show.main.subprocess.Popen',
                mock.MagicMock()) as mock_popen:
            mock_proc = MagicMock()
            mock_proc.communicate = MagicMock(return_value=(None, None))
            mock_proc.returncode = 1
            mock_popen.return_value = mock_proc
            result = CliRunner().invoke(show.cli.commands['runningconfiguration'].commands['all'], [])
        assert result.exit_code != 0
        assert "Aborted" in result.output

    @classmethod
    def teardown_class(cls):
        print("TEARDOWN")
        os.environ["PATH"] = os.pathsep.join(os.environ["PATH"].split(os.pathsep)[:-1])
        os.environ["UTILITIES_UNIT_TESTING"] = "0"


class TestShowRunAllCommands(object):
    @classmethod
    def setup_class(cls):
        print("SETUP")
        os.environ["UTILITIES_UNIT_TESTING"] = "1"

    def test_show_runningconfiguration_all_json_loads_failure(self):
        def get_cmd_output_side_effect(*args, **kwargs):
            return ""
        with mock.patch('show.main.get_cmd_output',
                mock.MagicMock(side_effect=get_cmd_output_side_effect)) as mock_get_cmd_output:
            result = CliRunner().invoke(show.cli.commands['runningconfiguration'].commands['all'], [])
        assert result.exit_code != 0

    def test_show_runningconfiguration_all(self):
        def get_cmd_output_side_effect(*args, **kwargs):
            return "{}"
        with mock.patch('show.main.get_cmd_output',
                mock.MagicMock(side_effect=get_cmd_output_side_effect)) as mock_get_cmd_output:
            result = CliRunner().invoke(show.cli.commands['runningconfiguration'].commands['all'], [])
        assert mock_get_cmd_output.call_count == 2
        assert mock_get_cmd_output.call_args_list == [
            call('sonic-cfggen -d --print-data'),
            call("rvtysh -c 'show running-config'")]

    @classmethod
    def teardown_class(cls):
        print("TEARDOWN")
        os.environ["PATH"] = os.pathsep.join(os.environ["PATH"].split(os.pathsep)[:-1])
        os.environ["UTILITIES_UNIT_TESTING"] = "0"
