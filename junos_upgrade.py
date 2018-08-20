#!/opt/ipeng/ENV/bin/python3
"""
    This script is designed to upgrade JUNOS routers.
    Running this script will be service impacting.
    John Tishey - 2018
"""

import os, sys, logging, time
from jnpr.junos import Device
from jnpr.junos.utils.scp import SCP
from jnpr.junos.utils.sw import SW
from jnpr.junos.utils.config import Config
from jnpr.junos.exception import ConnectError
import xmltodict
from lxml import etree
import json
import CONFIG


class RunUpgrade(object):
    def __init__(self):
        self.arch = ''
        self.image = ''
        self.username = 'guest'
        self.password = 'password'
        self.set_enhanced_ip = False
        self.two_stage = False
        self.package = CONFIG.CODE_FOLDER + CONFIG.CODE_IMAGE64
        self.package32 = CONFIG.CODE_FOLDER + CONFIG.CODE_IMAGE32
        self.logfile = CONFIG.CODE_LOG


    def get_arguments(self):
        """ Handle input from CLI """
        try:
            self.host = sys.argv[1]
        except:
            print("""USAGE: junos_upgrade <device_hostname>

            This is a script to perform a software upgrade on a device running JUNOS.
            1. Get CLI Input / Print Usage Info
            2. Setup Logging / Ensure Image is on local server
            3. Open NETCONF Connection To Device
            4. Grab info on RE's
            5. Check For SW Image on Device - Copy if needed
            6. Request system snapshot
            7. Apply pre-upgrade config commands and check network-services mode
                8. Upgrade only RE
                   OR
                8. Start upgrade on backup RE 
                9. Perform an RE Switchover
                10. Perform upgrade on the other RE
            11. Re-check network services mode on MX and reboot if needed
            12. Apply post-upgrade config commands and switchover to RE0 if needed
            """)


    def initial_setup(self):
        # initialize logging
        logging.basicConfig(filename=CONFIG.CODE_LOG, level=logging.WARN,
                            format='%(asctime)s:%(name)s: %(message)s')
        logging.getLogger().name = self.host
        logging.getLogger().addHandler(logging.StreamHandler())
        logging.info('Information logged in {0}'.format(CONFIG.CODE_LOG))

        # verify package exists on local server
        if not (os.path.isfile(self.package)):
            msg = 'Software package does not exist: {0}. '.format(self.package)
            logging.error(msg)
            sys.exit()


    def open_connection(self):
        try:
            logging.warn('Connecting to ' + self.host + '...')
            self.dev = Device(host=self.host,
                              user=self.username,
                              password=self.password,
                              gather_facts=True)
            self.dev.open()
        except ConnectError as e:
            logging.error('Cannot connect to device: {0}'.format(e))
            exit(1)


    def collect_re_info(self):
        # Print info on each RE:
        if self.dev.facts['RE0']:
            logging.warn('' + self.host + ' ' + self.dev.facts['model'])
            logging.warn('-' * 24)
            if self.dev.facts['version_RE0']:
                logging.warn('             RE0  \t   RE1')
                logging.warn('Mastership: ' + \
                                 self.dev.facts['RE0']['mastership_state'] + '\t' + \
                                 self.dev.facts['RE1']['mastership_state'] + '')
                logging.warn('Status:     ' + \
                                 self.dev.facts['RE0']['status'] + '\t\t' + \
                                 self.dev.facts['RE1']['status'] + '')
                logging.warn('Model:      ' + \
                                 self.dev.facts['RE0']['model'] + '\t' + \
                                 self.dev.facts['RE1']['model'] + '')
                logging.warn('Version:    ' + \
                                 self.dev.facts['version_RE0'] + '\t' + \
                                 self.dev.facts['version_RE1'] + '')
            else:
                logging.warn('               RE0  ')
                logging.warn('Mastership: ' + \
                                 self.dev.facts['RE0']['mastership_state'] + '')
                logging.warn('Status:     ' + \
                                 self.dev.facts['RE0']['status'] + '')
                logging.warn('Model:      ' + \
                                 self.dev.facts['RE0']['model'] + '')
                logging.warn('Version:    ' + \
                                 self.dev.facts['version'] + '')
            logging.warn("")
    
            # Check for redundant REs
            logging.warn('Checking for redundant routing-engines...')
            if not self.dev.facts['2RE']:
                re_stop = input("Redundant RE's not found, Continue? (y/n): ")
                if re_stop.lower() != 'y':
                    self.dev.close()
                    exit()

      
    def copy_image(self, source, dest):
        """ Copy files via SCP """
        cont = input('Image not found on active RE, copy it now? (y/n): ')
        if cont.lower() != 'y':
            logging.warn('Exiting...')
            self.dev.close()
            exit()
        try:
            with SCP(self.dev, progress=True) as scp:
                logging.warn("Copying image to " + dest + "...")
                scp.put(source, remote_path=dest)
        except FileNotFoundError as e:
            logging.warn(str(e))
            logging.warn('ERROR: Local file "' + source + '" not found')
            self.dev.close()
            exit()


    def image_check(self):
        """ Check to make sure needed files are on the device and copy if needed,
            Currently only able to copy to the active RE """
        # Determine 32-bit or 64-bit:
        logging.warn('Checking for 32 or 64-bit code...')
        ver = xmltodict.parse(etree.tostring(
               self.dev.rpc.get_software_information(detail=True)))
        version_info = json.dumps(ver)
        if '64-bit' in version_info:
            self.arch = '64-bit'
        elif '32-bit' in version_info:
            self.arch = '32-bit'
        else:
            logging.warn("1. 32-bit Image")
            logging.warn("2. 64-bit Image")
            image_type = input("Select Image Type (1/2): ")
            if image_type == '1':
                self.arch = '32-bit'
                logging.warn('32-bit Code Selected')
            elif image_type == '2':
                self.arch = '64-bit'
                logging.warn('64-bit Code Selected')
            else:
                logging.warn("Please enter only 1 or 2")
                self.image_check()
                return

        # Define all the file names / paths
        if self.arch == '32-bit':
            source = CONFIG.CODE_FOLDER + CONFIG.CODE_IMAGE32
            dest = CONFIG.CODE_DEST + CONFIG.CODE_IMAGE32
            source_2stg = CONFIG.CODE_FOLDER + CONFIG.CODE_2STAGE32
            dest_2stg = CONFIG.CODE_DEST + CONFIG.CODE_2STAGE32
            source_jsu = CONFIG.CODE_FOLDER + CONFIG.CODE_JSU32
            dest_jsu = CONFIG.CODE_DEST + CONFIG.CODE_JSU32
        elif self.arch == '64-bit':
            source = CONFIG.CODE_FOLDER + CONFIG.CODE_IMAGE64
            dest = CONFIG.CODE_DEST + CONFIG.CODE_IMAGE64
            source_2stg = CONFIG.CODE_FOLDER + CONFIG.CODE_2STAGE64
            dest_2stg = CONFIG.CODE_DEST + CONFIG.CODE_2STAGE64
            source_jsu = CONFIG.CODE_FOLDER + CONFIG.CODE_JSU64
            dest_jsu = CONFIG.CODE_DEST + CONFIG.CODE_JSU64
        
        # Check for final software image on the device
        logging.warn('Checking for image on the active RE...')
        img = xmltodict.parse(etree.tostring(self.dev.rpc.file_list(path=dest)))
        img_output = json.dumps(img)
        # If image file does not exit - copy from server
        if 'No such file' in img_output:
            self.copy_image(source, dest)
    
        # If dual RE - Check backup RE too
        if self.dev.facts['2RE']:
            if self.dev.facts['master'] == 'RE0':
                backup_RE = 're1:/'
            else:
                backup_RE = 're0:/'

            # Check for final image file on backup RE
            logging.warn('Checking for image on the backup RE...')
            img = xmltodict.parse(etree.tostring(self.dev.rpc.file_list(path=backup_RE + dest)))
            img_output = json.dumps(img)
            # Cant copy to backup RE remotely, semd message and quit
            if 'No such file' in img_output:
                msg = 'file copy ' + source + ' ' + backup_RE + dest
                logging.warn('ERROR: Copy the image to the backup RE, then re-run script')
                logging.warn('CMD  : ' + msg)
                self.dev.close()
                exit()

        # If 2 stage upgrade, look for intermediate image
        if CONFIG.CODE_2STAGE32 or CONFIG.CODE_2STAGE64:
            if self.dev.facts['version'][:2] == CONFIG.CODE_2STAGEFOR:
                logging.warn('Two-Stage Upgrade will be performed...')
                self.two_stage = True

                # If file does not exist on the active RE, copy it now?
                logging.warn('Checking for 2-stage image on the active RE...')
                img = xmltodict.parse(etree.tostring(self.dev.rpc.file_list(path=dest_2stg)))                
                img_output = json.dumps(img)
                if 'No such file' in img_output:
                    self.copy_image(source_2stg, dest_2stg)

                # Check for intermediate image file on backup RE
                if self.dev.facts['2RE']:
                    logging.warn('Checking for 2-stage image on the backup RE...')
                    img = xmltodict.parse(etree.tostring(
                            self.dev.rpc.file_list(path=backup_RE + dest_2stg)))
                    img_output = json.dumps(img)
                    if 'No such file' in img_output:
                        msg = 'file copy ' + source_2stg + ' ' + backup_RE + dest_2stg
                        logging.warn('ERROR: Copy the intermediate image to the backup RE, then re-run script')
                        logging.warn('CMD  : ' + msg)
                        self.dev.close()
                        exit()

        # Check if JSU Install is requested
        if CONFIG.CODE_JSU32 or CONFIG.CODE_JSU64:
            # Check for the JSU on the active RE
            logging.warn('Checking for JSU on the active RE...')
            img = xmltodict.parse(etree.tostring(self.dev.rpc.file_list(path=dest_jsu)))                
            img_output = json.dumps(img)
            if 'No such file' in img_output:
                self.copy_image(source_jsu, dest_jsu)

            # Check for the JSU on the backup RE
            if self.dev.facts['2RE']:
                logging.warn('Checking for JSU on the backup RE...')
                img = xmltodict.parse(etree.tostring(
                        self.dev.rpc.file_list(path=backup_RE + dest_jsu)))
                img_output = json.dumps(img)
                if 'No such file' in img_output:
                    msg = 'file copy ' + source_jsu + ' ' + backup_RE + dest_jsu
                    logging.warn('ERROR: Copy the JSU to the backup RE, then re-run script')
                    logging.warn('CMD  : ' + msg)
                    self.dev.close()
                    exit()


    def system_snapshot(self):
        """ Performs [request system snapshot] on the device """
        logging.warn('Requesting system snapshot...')
        self.dev.rpc.request_snapshot()


    def remove_traffic(self):
        """ Removes chassis redundancy and PIM NSR disable, as well as  overrides ISIS  """
        config_cmds = CONFIG.PRE_UPGRADE_CMDS
        # Network Service check on MX Platform
        if config_cmds:
            if self.dev.facts['model'][:2] == 'MX':
                net_mode = xmltodict.parse(etree.tostring(
                            self.dev.rpc.network_services()))
                cur_mode = net_mode['network-services']['network-services-information']['name']
                if cur_mode != 'Enhanced-IP':
                    logging.warn('Network Services mode is ' + cur_mode + '')
                    cont = input('Change Network Services Mode to Enhanced-IP? (y/n): ')
                    if cont.lower() == 'y':
                        config_cmds.append('set chassis network-services enhanced-ip')
                        # Set a flag to recheck at the end and reboot if needed:
                        self.set_enhanced_ip = True

            # Make configuration changes
            logging.warn('Entering Configuration Mode...')
            logging.warn('-' * 24)

            try:
                with Config(self.dev, mode='exclusive') as cu:
                    for cmd in config_cmds:
                        cu.load(cmd, merge=True, ignore_warning=True)
                    logging.warn("Configuration Changes:")
                    logging.warn('-' * 24)
                    cu.pdiff()
                    if cu.diff():
                        cont = input('Commit Changes? (y/n): ')
                        if cont.lower() != 'y':
                            logging.warn('Rolling back changes...')
                            cu.rollback(rb_id=0)
                            exit()
                        else:
                            cu.commit()
                    else:
                        cont = input('No changes found to commit.  Continue upgrading router? (y/n): ')
                        if cont.lower() != 'y':
                            exit()
            except RuntimeError as e:
                if "Ex: format='set'" in str(e):
                    logging.warn('ERROR: Unable to parse the PRE_UPGRADE_CMDS')
                    logging.warn('       Make sure they are formatted correctly.')
                else:
                    logging.warn('ERROR: {0}'.format(e))
                self.dev.close()
                exit()


    def upgrade_backup_re(self):
        """ Cycle through installing packcages for Dual RE systems """
        cont = input("Continue with software add / reboot on backup RE? (y/n): ")
        if cont.lower() != 'y':
            res = input('Restore config changes before exiting? (y/n): ')
            if res.lower() == 'y':
                self.restore_traffic()
            self.dev.close()
            exit()
        # First Stage Upgrade
        if self.two_stage:
            self.backup_re_pkg_add(CONFIG.CODE_2STAGE32, CONFIG.CODE_2STAGE64, CONFIG.CODE_PRESERVE)
        # Second Stage Upgrade
        self.backup_re_pkg_add(CONFIG.CODE_IMAGE32, CONFIG.CODE_IMAGE64, CONFIG.CODE_DEST)
        # JSU Upgrade
        if CONFIG.CODE_JSU32 or CONFIG.CODE_JSU64:
            if self.two_stage:
                self.backup_re_pkg_add(CONFIG.CODE_JSU32, CONFIG.CODE_JSU64, CONFIG.CODE_PRESERVE)
            else:
                self.backup_re_pkg_add(CONFIG.CODE_JSU32, CONFIG.CODE_JSU64, CONFIG.CODE_DEST)

   
    def backup_re_pkg_add(self, PKG32, PKG64, R_PATH):
        """ Perform software add and reboot the back RE """
        self.dev.timeout = 3600
        # Figure which RE is the current backup
        RE0, RE1 = False, False
        if self.dev.facts['master'] == 'RE0' and \
                    'backup' in self.dev.facts['RE1'].values():
            backup_RE = 'RE1'
            RE1 = True
        elif self.dev.facts['master'] == 'RE1' and \
                    'backup' in self.dev.facts['RE0'].values():
            backup_RE = 'RE0'
            RE0 = True
        else:
            logging.warn("Trouble finding the backup RE...")
            self.dev.close()
            exit()

        # Assign package path and name
        if self.arch == '32-bit':
            PACKAGE = PKG32
        else:
            PACKAGE = PKG64

        # Add package and reboot the backup RE
        logging.warn('Installing ' + PACKAGE + ' on ' + backup_RE + '...')
        ok = SW(self.dev).install(package=PACKAGE, validate=False, reboot=True, no_copy=True,
                        progress=True, all_re=False, re0=RE0, re1=RE1, remote_path=R_PATH)

        if not ok:
            logging.warn('Encountered issues with software add...  Exiting')
            cont = input('Rollback configuration changes? (y/n): ')
            if cont.lower() == 'y':
                self.restore_traffic()
            self.dev.close()
            exit()

        # Wait 2 minutes for package to install / reboot, then start checking every 30s
        time.sleep(120)
        re_state = 'Present'
        while re_state == 'Present':
            time.sleep(30)
            re_state = xmltodict.parse(etree.tostring(
                    self.dev.rpc.get_route_engine_information()))['route-engine-information']\
                    ['route-engine'][int(backup_RE[-1])]['mastership-state']
                
        # Give it 20 seconds, then check status
        time.sleep(20)
        re_status = xmltodict.parse(etree.tostring(
                self.dev.rpc.get_route_engine_information()))['route-engine-information']\
                ['route-engine'][int(backup_RE[-1])]['status']
        if re_status != 'OK':
            logging.warn('Backup RE state  = ' + re_state)
            logging.warn('Backup RE status = ' + re_status)

        # Grab core dump and SW version info
        self.dev.facts_refresh()
        if backup_RE == 'RE0':
            core_dump =  xmltodict.parse(etree.tostring(self.dev.rpc.get_system_core_dumps(re0=True)))
            sw_version = xmltodict.parse(etree.tostring(self.dev.rpc.get_software_information(re0=True)))
        elif backup_RE == 'RE1':
            core_dump =  xmltodict.parse(etree.tostring(self.dev.rpc.get_system_core_dumps(re1=True)))
            sw_version = xmltodict.parse(etree.tostring(self.dev.rpc.get_software_information(re1=True)))

        # Check for core dumps:
        logging.warn("Checking for core dumps...")
        for item in core_dump['multi-routing-engine-results']['multi-routing-engine-item']['directory-list']['output']:
            if 'No such file' not in item:
                logging.warn('Found Core Dumps!  Please investigate.')
                logging.warn(item + "")
                cont = input("Continue with upgrade? (y/n): ")
                if cont.lower() != 'y':
                    self.dev.close()
                    exit()
        # Check SW Version:
        logging.warn(backup_RE + ' software version = ' + \
            sw_version['multi-routing-engine-results']['multi-routing-engine-item']['software-information']['junos-version'])


    def upgrade_single_re(self):
        """ Cycle through installing packcages for single RE systems """
        logging.warn("-----------------------------------------------------------")
        logging.warn("|  Ready to upgrade, THIS WILL BE SERVICE IMPACTING!!!    |")
        logging.warn("-----------------------------------------------------------")
        cont = input("Continue with software add / reboot? (y/n): ")
        if cont.lower() != 'y':
            res = input('Restore config changes before exiting? (y/n): ')
            if res.lower() == 'y':
                self.restore_traffic()
            self.dev.close()
            exit() 
        # First Stage Upgrade
        if self.two_stage:
            self.single_re_pkg_add(CONFIG.CODE_2STAGE32, CONFIG.CODE_2STAGE64, CONFIG.CODE_PRESERVE)
        # Second Stage Upgrade
        self.single_re_pkg_add(CONFIG.CODE_IMAGE32, CONFIG.CODE_IMAGE64, CONFIG.CODE_DEST)
        # JSU Upgrade
        if CONFIG.CODE_JSU32 or CONFIG.CODE_JSU64:
            if self.two_stage:
                self.single_re_pkg_add(CONFIG.CODE_JSU32, CONFIG.CODE_JSU64, CONFIG.CODE_PRESERVE)
            else:
                self.single_re_pkg_add(CONFIG.CODE_JSU32, CONFIG.CODE_JSU64, CONFIG.CODE_DEST)


    def single_re_pkg_add(self, PKG32, PKG64, R_PATH):
        """ Perform software add and reboot the RE / Device """
        self.dev.timeout = 3600
        if self.arch == '32-bit':
            PACKAGE = PKG32
        else:
            PACKAGE = PKG64

        # Request package add
        logging.warn('Upgrading device... Please Wait...')
            
        ok = SW(self.dev).install(package=PACKAGE, validate=False, reboot=True, no_copy=True,
                        progress=True, remote_path=R_PATH)
        if not ok:    
            logging.warn('Encountered issues with software add...  Exiting')
            cont = input("Restore configuration before exiting? (y/n): ")
            if cont.lower() == 'y':
                self.restore_traffic()
            self.dev.close()
            exit()
        logging.warn('sw reuslt = ' + str(ok))
        exit()
        # Wait 2 minutes for package to install and reboot, then start checking every 30s
        time.sleep(120)
        while self.dev.probe() == False:
            time.sleep(30)

        # Once dev is reachable, re-open connection (refresh facts first to kill conn)
        self.dev.facts_refresh()
        self.dev.open()
        self.dev.facts_refresh()

        # Check for core dumps:
        logging.warn("Checking for core dumps...")
        core_dump =  xmltodict.parse(etree.tostring(self.dev.rpc.get_system_core_dumps()))    
        for item in core_dump['multi-routing-engine-results']['multi-routing-engine-item']['directory-list']['output']:
            if 'No such file' not in item:
                logging.warn('Found Core Dumps!  Please investigate.')
                logging.warn(item)
                cont = input("Continue with upgrade? (y/n): ")
                if cont.lower() != 'y':
                    self.dev.close()
                    exit()
        # Check SW Version:
        logging.warn('SW Version: ' + self.dev.facts['version'] + '')


    def switchover_RE(self):
        """ Issue RE switchover """
        if self.dev.facts['2RE']:
            logging.warn("-----------------------------------------------------------")
            logging.warn("|  Switch to backup RE, THIS WILL BE SERVICE IMPACTING!!! |")
            logging.warn("-----------------------------------------------------------")
            cont = input('Continue with switchover? (y/n): ')
            if cont.lower() != 'y':
                logging.warn("Exiting...")
                self.dev.close()
                exit()
            
            # Using dev.cli because I couldn't find an RPC call for switchover
            self.dev.timeout = 20
            logging.warn("Performing switchover to backup RE...")
            self.dev.cli('request chassis routing-engine master switch no-confirm')
            time.sleep(15)
            while self.dev.probe() == False:
                time.sleep(10)

            # Once dev is reachable, re-open connection (refresh facts first to kill conn)
            self.dev.facts_refresh()
            self.dev.open()
            self.dev.facts_refresh()

            # Add a check for task replication
            logging.warn('Checking task replication...')
            rep = xmltodict.parse(etree.tostring(
                    self.dev.rpc.get_routing_task_replication_state()))
            for k, v in rep['task-replication-state'].items():
                if v != 'Complete':
                    logging.warn('Protocol ' + k + ' is ' + v + '')


    def mx_network_services(self):
        """ Check if network-services mode enhanced-ip was requested, and set, reboot if not"""
        if self.dev.facts['model'][:2] == 'MX':
            if self.mx_network_services:
                cont = input('Reboot both REs now to set network-services mode enhanced-ip? (y/n): ')
                if cont.lower() == 'y':
                    logging.warn('Rbooting ' + self.host + '... Please wait...')
                    self.dev.timeout = 3600
                    self.dev.rpc.request_reboot(routing_engine='both-routing-engines')
                    # Wait 2 minutes for reboot, then start checking every 30s
                    time.sleep(120)
                    while self.dev.probe() == False:
                        time.sleep(30)
                    self.dev.facts_refresh()
                    self.dev.open()
                    self.dev.facts_refresh()


    def restore_traffic(self):
        """ Verify version, restore config, and wait for replication on dualRE """
        # Check SW Version:
        if self.dev.facts['2RE']:
            self.collect_re_info()
            if self.dev.facts['version_RE0'] == self.dev.facts['version_RE1']:
                logging.warn('Version matches on both routing engines.')
            else:
                logging.warn('ERROR: Versions do not match on both routing engines')
                logging.warn('Exiting script, please check device status manually.')
                self.dev.close()
                exit()

        logging.warn('Restoring configruation...')
        config_cmds = CONFIG.POST_UPGRADE_CMDS

        with Config(self.dev, mode='exclusive') as cu:
            for cmd in config_cmds:
                cu.load(cmd, merge=True, ignore_warning=True)
            logging.warn("Configuration Changes:")
            logging.warn('-' * 24)
            cu.pdiff()
            if cu.diff():
                cont = input('Commit Changes? (y/n): ')
                if cont.lower() != 'y':
                    logging.warn('Rolling back changes...')
                    cu.rollback(rb_id=0)
                    exit()
                else:
                    cu.commit()
            else:
                cont = input('No changes found to commit...')
        
        
    def switch_to_master(self):
        """ Switch back to the default master - RE0 """
        # Add a check for task replication
        if self.dev.facts['2RE']:
            logging.warn('Checking task replication...')
            task_sync = False
            while task_sync == False:
                rep = xmltodict.parse(etree.tostring(
                        self.dev.rpc.get_routing_task_replication_state()))
                task_sync = True
                for k, v in rep['task-replication-state'].items():
                    if v == 'InProgress':
                        task_sync = False
                        logging.warn('Protocol ' + k + ' is ' + v + '...  Waiting 2 minutes...')
                if task_sync == False:
                    time.sleep(120)

            # Check which RE is active and switchover if needed
            if self.dev.facts['re_master']['default'] == '1':
                cont = input('Task replication complete, switchover to RE0? (y/n): ')
                if cont.lower() == 'y':
                    self.dev.timeout = 20
                    logging.warn("Performing final switchover to RE0...")
                    self.dev.cli('request chassis routing-engine master switch no-confirm')
                    time.sleep(15)
                    while self.dev.probe() == False:
                        time.sleep(10)
                    self.dev.facts_refresh()
                    self.dev.open()
                    self.dev.facts_refresh()



execute = RunUpgrade()

# 1. Get CLI Input / Print Usage Info
execute.get_arguments()
# 2. Setup Logging / Ensure Image is on local server
execute.initial_setup()
# 3. Open NETCONF Connection To Device
execute.open_connection()
# 4. Grab info on RE's
execute.collect_re_info()
# 5. Check For SW Image(s) on Device - Copy if needed
execute.image_check()
# 6. Request system snapshot
execute.system_snapshot()
# 7. Remove Redundancy / NSR, Overload ISIS, and check for Enhanced-IP
execute.remove_traffic()

# IF DEVICE IS SINGLE RE
if not execute.dev.facts['2RE']:
    # 8. Upgrade only RE
    execute.upgrade_single_re()
# IF DEVICE IS DUAL RE
else:
    # 8. Start upgrade on backup RE
    execute.upgrade_backup_re()
    # 9. Perform an RE Switchover
    execute.switchover_RE()
    # 10. Perform upgrade on the other RE
    execute.upgrade_backup_re()

# 11. Re-check network services mode on MX and reboot if needed
execute.mx_network_services()
# 12. Restore Routing-Engine redundancy
execute.restore_traffic()
#13. Switch back to RE0
execute.switch_to_master()

execute.dev.close()
logging.warn("Upgrade script complete, have a nice day!")