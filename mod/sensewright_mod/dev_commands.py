# Sensewright v2 - Dev Commands
# Python 3.7 compatible

import sims4.commands
from sensewright_mod.dev_manager import SensewrightDevManager

@sims4.commands.Command('sw.master', command_type=sims4.commands.CommandType.Live)
def _sw_master_command(enable: str = None, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    
    if enable is not None:
        state = (enable.lower() in ('1', 'true', 'on', 'yes'))
        if state:
            SensewrightDevManager.enable_dev_mode()
        else:
            SensewrightDevManager.disable_dev_mode()
    else:
        if SensewrightDevManager.dev_mode_enabled:
            SensewrightDevManager.disable_dev_mode()
        else:
            SensewrightDevManager.enable_dev_mode()
    
    state_str = "ENABLED" if SensewrightDevManager.dev_mode_enabled else "DISABLED"
    output("Sensewright Dev Mode: {}".format(state_str))
    
    # Visual feedback in the game
    try:
        from sims4communitylib.notifications.common_basic_notification import CommonBasicNotification
        from sims4communitylib.utils.localization.common_localization_utils import CommonLocalizationUtils
        CommonBasicNotification(
            CommonLocalizationUtils.create_localized_string("Sensewright Dev Mode"),
            CommonLocalizationUtils.create_localized_string("Dev mode is now {}.".format(state_str))
        ).show()
    except Exception:
        pass
