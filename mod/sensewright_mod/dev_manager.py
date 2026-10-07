# sensewright_mod/dev_manager.py

class SensewrightDevManager:
    """Manages the developer mode states and debug toggles."""
    
    # Global switch for the entire Dev UI
    dev_mode_enabled = False
    
    # Granular debug toggles (passive notifications/logs)
    debug_sim_enabled = False
    debug_god_enabled = False
    debug_sys_enabled = False

    @classmethod
    def enable_dev_mode(cls):
        cls.dev_mode_enabled = True
        
    @classmethod
    def disable_dev_mode(cls):
        cls.dev_mode_enabled = False
        # Optional: Disable all child debug states when turning off dev mode?
        # Actually it's better to keep their states so if they turn dev mode back on, it remembers.

    @classmethod
    def toggle_debug_sim(cls) -> bool:
        cls.debug_sim_enabled = not cls.debug_sim_enabled
        return cls.debug_sim_enabled

    @classmethod
    def toggle_debug_god(cls) -> bool:
        cls.debug_god_enabled = not cls.debug_god_enabled
        return cls.debug_god_enabled

    @classmethod
    def toggle_debug_sys(cls) -> bool:
        cls.debug_sys_enabled = not cls.debug_sys_enabled
        return cls.debug_sys_enabled
