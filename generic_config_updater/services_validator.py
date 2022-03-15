import os
import time
from .gu_common import genericUpdaterLogging

logger = genericUpdaterLogging.get_logger(title="Service Validator")

print_to_console = False

def set_verbose(verbose=False):
    global print_to_console, logger

    print_to_console = verbose
    if verbose:
        logger.set_min_log_priority_debug()
    else:
        logger.set_min_log_priority_notice()


def _service_restart(svc_name):
    rc = os.system(f"systemctl restart {svc_name}")
    if rc != 0:
        # This failure is likely due to too many restarts
        #
        rc = os.system(f"systemctl reset-failed {svc_name}")
        logger.log(logger.LOG_PRIORITY_ERROR, 
                f"Service has been reset. rc={rc}; Try restart again...",
                print_to_console)

        rc = os.system(f"systemctl restart {svc_name}")
        if rc != 0:
            # Even with reset-failed, restart fails.
            # Give a pause before retry.
            #
            logger.log(logger.LOG_PRIORITY_ERROR,
                    f"Restart failed for {svc_name} rc={rc} after reset; Pause for 10s & retry",
                    print_to_console)
            time.sleep(10)
            rc = os.system(f"systemctl restart {svc_name}")

    if rc == 0:
        logger.log(logger.LOG_PRIORITY_NOTICE,
                f"Restart succeeded for {svc_name}",
                print_to_console)
    else:
        logger.log(logger.LOG_PRIORITY_ERROR,
                f"Restart failed for {svc_name} rc={rc}",
                print_to_console)
    return rc == 0


def rsyslog_validator(old_config, upd_config, keys):
    rc = os.system("/usr/bin/rsyslog-config.sh")
    if rc != 0:
        return _service_restart("rsyslog")
    else:
        return True


def dhcp_validator(old_config, upd_config, keys):
    return _service_restart("dhcp_relay")


def vlan_validator(old_config, upd_config, keys):
    old_vlan = old_config.get("VLAN", {})
    upd_vlan = upd_config.get("VLAN", {})

    for key in set(old_vlan.keys()).union(set(upd_vlan.keys())):
        if (old_vlan.get(key, {}).get("dhcp_servers", []) != 
                upd_vlan.get(key, {}).get("dhcp_servers", [])):
            return _service_restart("dhcp_relay")
    # No update to DHCP servers.
    return True

def caclrule_validator(old_config, upd_config, keys):
    old_caclrule = old_config.get("ACL_RULE", {})
    upd_caclrule = upd_config.get("ACL_RULE", {})

    for key in set(old_caclrule.keys()).union(set(upd_caclrule.keys())):
        if (old_caclrule.get(key, {}) != upd_caclrule.get(key, {})):
            # caclmgrd will update in 0.5 sec when configuration stops,
            # we sleep 1 sec to make sure it does update.
            rc = os.system("sleep 1s")
            return rc == 0
    # No update to ACL_RULE.
    return True

