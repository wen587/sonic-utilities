#!/usr/bin/env python
#
# lib.py
#
# Core library for command-line interface for interacting with platform components within SONiC
#

try:
    import os
    import json
    import socket
    import subprocess
    import time
    import urllib
    from collections import OrderedDict

    import click
    from log import LogHelper
    from sonic_py_common import device_info
    from tabulate import tabulate
    from urlparse import urlparse

    from . import Platform
except ImportError as e:
    raise ImportError("Required module not found: {}".format(str(e)))

# ========================= Constants ==========================================

TAB = "    "
EMPTY = ""
NA = "N/A"
NEWLINE = "\n"

# ========================= Variables ==========================================

log_helper = LogHelper()

# ========================= Helper classes =====================================

class URL(object):
    """
    URL
    """
    HTTP_PREFIX = [ "http://", "https://" ]
    HTTP_CODE_BASE = 100
    HTTP_4XX_CLIENT_ERRORS = 4

    PB_LABEL = "  "
    PB_INFO_SEPARATOR = " | "
    PB_FULL_TERMINAL_WIDTH = 0

    DOWNLOAD_TIMEOUT = 30
    DOWNLOAD_PATH_TEMPLATE = "/tmp/{}"

    def __init__(self, url):
        self.__url = url
        self.__pb = None
        self.__pb_bytes_num = 0
        self.__pb_force_show = True

    def __str__(self):
        return self.__url

    def __reporthook(self, count, block_size, total_size):
        if self.__pb is None:
            self.__pb = click.progressbar(
                label=self.PB_LABEL,
                length=total_size,
                show_eta=True,
                show_percent=True,
                info_sep=self.PB_INFO_SEPARATOR,
                width=self.PB_FULL_TERMINAL_WIDTH
            )

        self.__pb.update(count * block_size - self.__pb_bytes_num)
        self.__pb_bytes_num = count * block_size

        if self.__pb_force_show:
            time.sleep(1)
            self.__pb_force_show = False

    def __pb_reset(self):
        if self.__pb:
            self.__pb.render_finish()
            self.__pb = None

        self.__pb_bytes_num = 0
        self.__pb_force_show = True

    def __validate(self):
        # Check basic URL syntax
        if not self.__url.startswith(tuple(self.HTTP_PREFIX)):
            raise RuntimeError("URL is malformed: did not match expected prefix " + str(self.HTTP_PREFIX))

        response_code = None

        # Check URL existence
        try:
            urlfile = urllib.urlopen(self.__url)
            response_code = urlfile.getcode()
        except IOError:
            raise RuntimeError("Did not receive a response from remote machine")

        # Check for a 4xx response code which indicates a nonexistent URL
        if response_code / self.HTTP_CODE_BASE == self.HTTP_4XX_CLIENT_ERRORS:
            raise RuntimeError("Image file not found on remote machine")

    def get_url(self):
        return self.__url

    def is_url(self):
        if self.__url.startswith(tuple(self.HTTP_PREFIX)):
            return True

        return False

    def retrieve(self):
        self.__validate()

        result = urlparse(self.__url)
        basename = os.path.basename(result.path)

        default_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(self.DOWNLOAD_TIMEOUT)

        try:
            filename, headers = urllib.urlretrieve(
                self.__url,
                self.DOWNLOAD_PATH_TEMPLATE.format(basename),
                self.__reporthook
            )
        except:
            if os.path.exists(self.DOWNLOAD_PATH_TEMPLATE.format(basename)):
                os.remove(self.DOWNLOAD_PATH_TEMPLATE.format(basename))
            raise
        finally:
            socket.setdefaulttimeout(default_timeout)
            self.__pb_reset()

        return filename, headers

    url = property(fget=get_url)


class PlatformDataProvider(object):
    """
    PlatformDataProvider
    """
    def __init__(self):
        self.__platform = Platform()
        self.__chassis = self.__platform.get_chassis()

        self.chassis_component_map = self.__get_chassis_component_map()
        self.module_component_map = self.__get_module_component_map()

    def __get_chassis_component_map(self):
        chassis_component_map = OrderedDict()

        chassis_name = self.__chassis.get_name()
        chassis_component_map[chassis_name] = OrderedDict()

        component_list = self.chassis.get_all_components()
        for component in component_list:
            component_name = component.get_name()
            chassis_component_map[chassis_name][component_name] = component

        return chassis_component_map

    def __get_module_component_map(self):
        module_component_map = OrderedDict()

        module_list = self.__chassis.get_all_modules()
        for module in module_list:
            module_name = module.get_name()
            module_component_map[module_name] = OrderedDict()

            component_list = module.get_all_components()
            for component in component_list:
                component_name = component.get_name()
                module_component_map[module_name][component_name] = component

        return module_component_map

    def get_platform(self):
        return self.__platform

    def get_chassis(self):
        return self.__chassis

    def is_modular_chassis(self):
        return len(self.module_component_map) > 0

    def is_chassis_has_components(self):
        return self.__chassis.get_num_components() > 0

    platform = property(fget=get_platform)
    chassis = property(fget=get_chassis)


class SquashFs(object):
    """
    SquashFs
    """
    OS_PREFIX = "SONiC-OS-"

    FS_PATH_TEMPLATE = "/host/image-{}/fs.squashfs"
    FS_RW_TEMPLATE = "/host/image-{}/rw"
    FS_WORK_TEMPLATE = "/host/image-{}/work"
    FS_MOUNTPOINT_TEMPLATE = "/tmp/image-{}-fs"

    OVERLAY_MOUNTPOINT_TEMPLATE = "/tmp/image-{}-overlay"

    def __init__(self):
        image_stem = self.next_image.lstrip(self.OS_PREFIX)

        self.fs_path = self.FS_PATH_TEMPLATE.format(image_stem)
        self.fs_rw = self.FS_RW_TEMPLATE.format(image_stem)
        self.fs_work = self.FS_WORK_TEMPLATE.format(image_stem)
        self.fs_mountpoint = self.FS_MOUNTPOINT_TEMPLATE.format(image_stem)

        self.overlay_mountpoint = self.OVERLAY_MOUNTPOINT_TEMPLATE.format(image_stem)

    def get_current_image(self):
        cmd = "sonic-installer list | grep 'Current: ' | cut -f2 -d' '"
        output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, shell=True)

        return output.rstrip(NEWLINE)

    def get_next_image(self):
        cmd = "sonic-installer list | grep 'Next: ' | cut -f2 -d' '"
        output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, shell=True)

        return output.rstrip(NEWLINE)

    def is_next_boot_set(self):
        return self.current_image != self.next_image

    def mount_next_image_fs(self):
        if os.path.ismount(self.fs_mountpoint) or os.path.ismount(self.overlay_mountpoint):
            self.umount_next_image_fs()

        os.mkdir(self.fs_mountpoint)
        cmd = "mount -t squashfs {} {}".format(
            self.fs_path,
            self.fs_mountpoint
        )
        subprocess.check_call(cmd, shell=True)

        os.mkdir(self.overlay_mountpoint)
        cmd = "mount -n -r -t overlay -o lowerdir={},upperdir={},workdir={} overlay {}".format(
            self.fs_mountpoint,
            self.fs_rw,
            self.fs_work,
            self.overlay_mountpoint
        )
        subprocess.check_call(cmd, shell=True)

        return self.overlay_mountpoint

    def umount_next_image_fs(self):
        if os.path.ismount(self.overlay_mountpoint):
            cmd = "umount -rf {}".format(self.overlay_mountpoint)
            subprocess.check_call(cmd, shell=True)

        if os.path.exists(self.overlay_mountpoint):
            os.rmdir(self.overlay_mountpoint)

        if os.path.ismount(self.fs_mountpoint):
            cmd = "umount -rf {}".format(self.fs_mountpoint)
            subprocess.check_call(cmd, shell=True)

        if os.path.exists(self.fs_mountpoint):
            os.rmdir(self.fs_mountpoint)

    current_image = property(fget=get_current_image)
    next_image = property(fget=get_next_image)


class PlatformComponentsParser(object):
    """
    PlatformComponentsParser
    """
    PLATFORM_COMPONENTS_FILE = "platform_components.json"
    PLATFORM_COMPONENTS_PATH_TEMPLATE = "{}/usr/share/sonic/device/{}/{}"

    CHASSIS_KEY = "chassis"
    MODULE_KEY = "module"
    COMPONENT_KEY = "component"
    FIRMWARE_KEY = "firmware"
    VERSION_KEY = "version"

    UTF8_ENCODING = "utf-8"

    def __init__(self, is_modular_chassis):
        self.__is_modular_chassis = is_modular_chassis
        self.__chassis_component_map = OrderedDict()
        self.__module_component_map = OrderedDict()

    def __get_platform_components_path(self, root_path):
        return self.PLATFORM_COMPONENTS_PATH_TEMPLATE.format(
            root_path,
            device_info.get_platform(),
            self.PLATFORM_COMPONENTS_FILE
        )

    def __is_str(self, obj):
        return isinstance(obj, unicode) or isinstance(obj, str)

    def __is_dict(self, obj):
        return isinstance(obj, dict)

    def __parser_fail(self, msg):
        raise RuntimeError("Failed to parse \"{}\": {}".format(self.PLATFORM_COMPONENTS_FILE, msg))

    def __parser_platform_fail(self, msg):
        self.__parser_fail("invalid platform schema: {}".format(msg))

    def __parser_chassis_fail(self, msg):
        self.__parser_fail("invalid chassis schema: {}".format(msg))

    def __parser_module_fail(self, msg):
        self.__parser_fail("invalid module schema: {}".format(msg))

    def __parser_component_fail(self, msg):
        self.__parser_fail("invalid component schema: {}".format(msg))

    def __parse_component_section(self, section, component, is_module_component=False):
        if not self.__is_dict(component):
            self.__parser_component_fail("dictionary is expected: key={}".format(self.COMPONENT_KEY))

        if not component:
            return

        missing_key = None

        for key1, value1 in component.items():
            if not self.__is_dict(value1):
                self.__parser_component_fail("dictionary is expected: key={}".format(key1))

            if not is_module_component:
                self.__chassis_component_map[section][key1] = OrderedDict()
            else:
                self.__module_component_map[section][key1] = OrderedDict()

            if value1:
                if len(value1) != 1 and len(value1) != 2:
                    self.__parser_component_fail("unexpected number of records: key={}".format(key1))

                if self.FIRMWARE_KEY not in value1:
                    missing_key = self.FIRMWARE_KEY
                    break
                elif len(value1) == 2 and self.VERSION_KEY not in value1:
                    missing_key = self.VERSION_KEY
                    break

                for key2, value2 in value1.items():
                    if not self.__is_str(value2):
                        self.__parser_component_fail("string is expected: key={}".format(key2))

                if not is_module_component:
                    self.__chassis_component_map[section][key1] = value1
                else:
                    self.__module_component_map[section][key1] = value1

        if missing_key is not None:
            self.__parser_component_fail("\"{}\" key hasn't been found".format(missing_key))

    def __parse_chassis_section(self, chassis):
        self.__chassis_component_map = OrderedDict()

        if not self.__is_dict(chassis):
            self.__parser_chassis_fail("dictionary is expected: key={}".format(self.CHASSIS_KEY))

        if not chassis:
            self.__parser_chassis_fail("dictionary is empty: key={}".format(self.CHASSIS_KEY))

        if len(chassis) != 1:
            self.__parser_chassis_fail("unexpected number of records: key={}".format(self.CHASSIS_KEY))

        for key, value in chassis.items():
            if not self.__is_dict(value):
                self.__parser_chassis_fail("dictionary is expected: key={}".format(key))

            if not value:
                self.__parser_chassis_fail("dictionary is empty: key={}".format(key))

            if self.COMPONENT_KEY not in value:
                self.__parser_chassis_fail("\"{}\" key hasn't been found".format(self.COMPONENT_KEY))

            if len(value) != 1:
                self.__parser_chassis_fail("unexpected number of records: key={}".format(key))

            self.__chassis_component_map[key] = OrderedDict()
            self.__parse_component_section(key, value[self.COMPONENT_KEY])

    def __parse_module_section(self, module):
        self.__module_component_map = OrderedDict()

        if not self.__is_dict(module):
            self.__parser_module_fail("dictionary is expected: key={}".format(self.MODULE_KEY))

        if not module:
            self.__parser_module_fail("dictionary is empty: key={}".format(self.MODULE_KEY))

        for key, value in module.items():
            if not self.__is_dict(value):
                self.__parser_module_fail("dictionary is expected: key={}".format(key))

            if not value:
                self.__parser_module_fail("dictionary is empty: key={}".format(key))

            if self.COMPONENT_KEY not in value:
                self.__parser_module_fail("\"{}\" key hasn't been found".format(self.COMPONENT_KEY))

            if len(value) != 1:
                self.__parser_module_fail("unexpected number of records: key={}".format(key))

            self.__module_component_map[key] = OrderedDict()
            self.__parse_component_section(key, value[self.COMPONENT_KEY], True)

    def __deunicodify_hook(self, pairs):
        new_pairs = [ ]

        for key, value in pairs:
            if isinstance(key, unicode):
                key = key.encode(self.UTF8_ENCODING)

            if isinstance(value, unicode):
                value = value.encode(self.UTF8_ENCODING)

            new_pairs.append((key, value))

        return OrderedDict(new_pairs)

    def get_chassis_component_map(self):
        return self.__chassis_component_map

    def get_module_component_map(self):
        return self.__module_component_map

    def parse_platform_components(self, root_path=None):
        platform_components_path = None

        if root_path is None:
            platform_components_path = self.__get_platform_components_path(EMPTY)
        else:
            platform_components_path = self.__get_platform_components_path(root_path)

        with open(platform_components_path) as platform_components:
            data = json.load(platform_components, object_pairs_hook=self.__deunicodify_hook)

            if not self.__is_dict(data):
                self.__parser_platform_fail("dictionary is expected: key=root")

            if not data:
                self.__parser_platform_fail("dictionary is empty: key=root")

            if self.CHASSIS_KEY not in data:
                self.__parser_platform_fail("\"{}\" key hasn't been found".format(self.CHASSIS_KEY))

            if not self.__is_modular_chassis:
                if len(data) != 1:
                    self.__parser_platform_fail("unexpected number of records: key=root")

            self.__parse_chassis_section(data[self.CHASSIS_KEY])

            if self.__is_modular_chassis:
                if self.MODULE_KEY not in data:
                    self.__parser_platform_fail("\"{}\" key hasn't been found".format(self.MODULE_KEY))

                if len(data) != 2:
                    self.__parser_platform_fail("unexpected number of records: key=root")

                self.__parse_module_section(data[self.MODULE_KEY])

    chassis_component_map = property(fget=get_chassis_component_map)
    module_component_map = property(fget=get_module_component_map)


class ComponentUpdateProvider(PlatformDataProvider):
    """
    ComponentUpdateProvider
    """
    STATUS_HEADER = [ "Chassis", "Module", "Component", "Firmware", "Version (Current/Available)", "Status" ]
    FORMAT = "simple"

    FW_STATUS_UPDATE_REQUIRED = "update is required"
    FW_STATUS_UP_TO_DATE = "up-to-date"

    SECTION_CHASSIS = "Chassis"
    SECTION_MODULE = "Module"

    def __init__(self, root_path=None):
        PlatformDataProvider.__init__(self)

        self.__root_path = root_path

        self.__pcp = PlatformComponentsParser(self.is_modular_chassis())
        self.__pcp.parse_platform_components(root_path)

        self.__validate_platform_schema(self.__pcp)

    def __diff_keys(self, keys1, keys2):
        return set(keys1) ^ set(keys2)

    def __validate_component_map(self, section, pdp_map, pcp_map):
        diff_keys = self.__diff_keys(pdp_map.keys(), pcp_map.keys())

        if diff_keys:
            raise RuntimeError(
                "{} names mismatch: keys={}".format(
                    section,
                    str(list(diff_keys))
                )
            )

        for key in pdp_map.keys():
            diff_keys = self.__diff_keys(pdp_map[key].keys(), pcp_map[key].keys())

            if diff_keys:
                raise RuntimeError(
                    "{} component names mismatch: keys={}".format(
                        section,
                        str(list(diff_keys))
                    )
                )

    def __validate_platform_schema(self, pcp):
        self.__validate_component_map(
            self.SECTION_CHASSIS,
            self.chassis_component_map,
            pcp.chassis_component_map
        )

        self.__validate_component_map(
            self.SECTION_MODULE,
            self.module_component_map,
            pcp.module_component_map
        )

    def get_status(self):
        status_table = [ ]

        append_chassis_name = self.is_chassis_has_components()
        append_module_na = not self.is_modular_chassis()
        module_name = NA

        for chassis_name, chassis_component_map in self.chassis_component_map.items():
            for chassis_component_name, chassis_component in chassis_component_map.items():
                component = self.__pcp.chassis_component_map[chassis_name][chassis_component_name]

                if component:
                    firmware_path = component[self.__pcp.FIRMWARE_KEY]

                    if self.__root_path is not None:
                        firmware_path = self.__root_path + firmware_path

                    firmware_version_current = chassis_component.get_firmware_version()

                    if self.__pcp.VERSION_KEY in component:
                        firmware_version_available = component[self.__pcp.VERSION_KEY]
                    else:
                        firmware_version_available = chassis_component.get_available_firmware_version(firmware_path)

                    if self.__root_path is not None:
                        firmware_path = component[self.__pcp.FIRMWARE_KEY]

                    firmware_version = "{} / {}".format(firmware_version_current, firmware_version_available)

                    if firmware_version_current != firmware_version_available:
                        status = self.FW_STATUS_UPDATE_REQUIRED
                    else:
                        status = self.FW_STATUS_UP_TO_DATE

                    status_table.append(
                        [
                            chassis_name if append_chassis_name else EMPTY,
                            module_name if append_module_na else EMPTY,
                            chassis_component_name,
                            firmware_path,
                            firmware_version,
                            status
                        ]
                    )

                    if append_chassis_name:
                        append_chassis_name = False

                    if append_module_na:
                        append_module_na = False

        append_chassis_name = not self.is_chassis_has_components()
        chassis_name = self.chassis.get_name()

        if self.is_modular_chassis():
            for module_name, module_component_map in self.module_component_map.items():
                append_module_name = True

                for module_component_name, module_component in module_component_map.items():
                    component = self.__pcp.module_component_map[module_name][module_component_name]

                    if component:
                        firmware_path = component[self.__pcp.FIRMWARE_KEY]

                        if self.__root_path is not None:
                            firmware_path = self.__root_path + firmware_path

                        firmware_version_current = module_component.get_firmware_version()

                        if self.__pcp.VERSION_KEY in component:
                            firmware_version_available = component[self.__pcp.VERSION_KEY]
                        else:
                            firmware_version_available = module_component.get_available_firmware_version(firmware_path)

                        if self.__root_path is not None:
                            firmware_path = component[self.__pcp.FIRMWARE_KEY]

                        firmware_version = "{} / {}".format(firmware_version_current, firmware_version_available)

                        if firmware_version_current != firmware_version_available:
                            status = self.FW_STATUS_UPDATE_REQUIRED
                        else:
                            status = self.FW_STATUS_UP_TO_DATE

                        status_table.append(
                            [
                                chassis_name if append_chassis_name else EMPTY,
                                module_name if append_module_name else EMPTY,
                                module_component_name,
                                firmware_path,
                                firmware_version,
                                status
                            ]
                        )

                        if append_chassis_name:
                            append_chassis_name = False

                        if append_module_name:
                            append_module_name = False

        if not status_table:
            return None

        return tabulate(status_table, self.STATUS_HEADER, tablefmt=self.FORMAT)

    def get_notification(self, chassis_name, module_name, component_name):
        if self.is_modular_chassis():
            component = self.module_component_map[module_name][component_name]
            parser = self.__pcp.module_component_map[module_name][component_name]
        else:
            component = self.chassis_component_map[chassis_name][component_name]
            parser = self.__pcp.chassis_component_map[chassis_name][component_name]

        if not parser:
            return None

        firmware_path = parser[self.__pcp.FIRMWARE_KEY]

        if self.__root_path is not None:
            firmware_path = self.__root_path + firmware_path

        return component.get_firmware_update_notification(firmware_path)

    def update_firmware(self, chassis_name, module_name, component_name):
        if self.is_modular_chassis():
            component = self.module_component_map[module_name][component_name]
            parser = self.__pcp.module_component_map[module_name][component_name]

            component_path = "{}/{}/{}".format(chassis_name, module_name, component_name)
        else:
            component = self.chassis_component_map[chassis_name][component_name]
            parser = self.__pcp.chassis_component_map[chassis_name][component_name]

            component_path = "{}/{}".format(chassis_name, component_name)

        if not parser:
            return

        firmware_path = parser[self.__pcp.FIRMWARE_KEY]

        if self.__root_path is not None:
            firmware_path = self.__root_path + firmware_path

        try:
            click.echo("Updating firmware:")
            click.echo(TAB + firmware_path)
            log_helper.log_fw_update_start(component_path, firmware_path)
            component.update_firmware(firmware_path)
            log_helper.log_fw_update_end(component_path, firmware_path, True)
        except KeyboardInterrupt:
            log_helper.log_fw_update_end(component_path, firmware_path, False, "Keyboard interrupt")
            raise
        except Exception as e:
            log_helper.log_fw_update_end(component_path, firmware_path, False, e)
            raise

    def is_firmware_update_available(self, chassis_name, module_name, component_name):
        if self.is_modular_chassis():
            component = self.__pcp.module_component_map[module_name][component_name]
        else:
            component = self.__pcp.chassis_component_map[chassis_name][component_name]

        if not component:
            return False

        return True

    def is_firmware_update_required(self, chassis_name, module_name, component_name):
        if self.is_modular_chassis():
            component = self.module_component_map[module_name][component_name]
            parser = self.__pcp.module_component_map[module_name][component_name]
        else:
            component = self.chassis_component_map[chassis_name][component_name]
            parser = self.__pcp.chassis_component_map[chassis_name][component_name]

        if not parser:
            return False

        firmware_path = parser[self.__pcp.FIRMWARE_KEY]

        if self.__root_path is not None:
            firmware_path = self.__root_path + firmware_path

        firmware_version_current = component.get_firmware_version()

        if self.__pcp.VERSION_KEY in parser:
            firmware_version_available = parser[self.__pcp.VERSION_KEY]
        else:
            firmware_version_available = component.get_available_firmware_version(firmware_path)

        return firmware_version_current != firmware_version_available


class ComponentStatusProvider(PlatformDataProvider):
    """
    ComponentStatusProvider
    """
    HEADER = [ "Chassis", "Module", "Component", "Version", "Description" ]
    FORMAT = "simple"

    def __init__(self):
        PlatformDataProvider.__init__(self)

    def get_status(self):
        status_table = [ ]

        append_chassis_name = self.is_chassis_has_components()
        append_module_na = not self.is_modular_chassis()
        module_name = NA

        for chassis_name, chassis_component_map in self.chassis_component_map.items():
            for chassis_component_name, chassis_component in chassis_component_map.items():
                firmware_version = chassis_component.get_firmware_version()
                description = chassis_component.get_description()

                status_table.append(
                    [
                        chassis_name if append_chassis_name else EMPTY,
                        module_name if append_module_na else EMPTY,
                        chassis_component_name,
                        firmware_version,
                        description
                    ]
                )

                if append_chassis_name:
                    append_chassis_name = False

                if append_module_na:
                    append_module_na = False

        append_chassis_name = not self.is_chassis_has_components()
        chassis_name = self.chassis.get_name()

        if self.is_modular_chassis():
            for module_name, module_component_map in self.module_component_map.items():
                append_module_name = True

                for module_component_name, module_component in module_component_map.items():
                    firmware_version = module_component.get_firmware_version()
                    description = module_component.get_description()

                    status_table.append(
                        [
                            chassis_name if append_chassis_name else EMPTY,
                            module_name if append_module_name else EMPTY,
                            module_component_name,
                            firmware_version,
                            description
                        ]
                    )

                    if append_chassis_name:
                        append_chassis_name = False

                    if append_module_name:
                        append_module_name = False

        return tabulate(status_table, self.HEADER, tablefmt=self.FORMAT)