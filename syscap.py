#!/usr/bin/env python3

import os
import sys
import shutil
import logging
from glob import glob
import json
import argparse
import subprocess as sproc


class SysCap(object):

    def __init__(self, options):
        self.config = options['config']
        self.base_dir = options['base_dir']
        self.phase = options['phase']
        self.verbose = options['verbose']
        self.overwrite = options['overwrite']
        self.data_dir = os.path.join(self.base_dir, options['tag_dir'])

        _log_level = {True: logging.DEBUG, False: logging.WARN}
        logging.basicConfig(format='%(levelname)s:%(module)s.%(funcName)s:%(message)s',
                            level=_log_level[self.verbose])
        self.logger = logging.getLogger()

    def initialise(self):
        """Build out the default config if it doens't exist already"""
        default_config = {
            "command_groups": [{
                "require": "/usr/bin/ls",
                "exec": ["/usr/bin/ls -la"],
                "outfile": "ls"
            }, {
                "exec": ["/sbin/ip -4 a s", "/sbin/ip route show"],
                "outfile": "network"
            }, {
                "exec": ["/usr/bin/df -TP", "/usr/bin/lsblk"],
                "outfile": "storage"
            }],
            "file_list": ["/etc/hosts", "/etc/hostname", "/etc/wgetrc", "/etc/rsyncd.conf"]
        }
        if not os.path.isfile(self.config) or self.overwrite:
            with open(self.config, 'w') as outfile_stream:
                try:
                    json.dump(default_config, outfile_stream, indent=2)
                    os.chmod(self.config, 0o640)
                    self.logger.error(f'Writing config to {self.config}')
                except OSError as exc:
                    self.logger.error(f'Writing config to {self.config}: {exc.strerror}')
                    sys.exit(1)
        else:
            self.logger.warning(f'Outfile {self.config} exists and overwrite (-o) not '
                                'specified... skipping initialising config file')

    def _createOutputStructure(self):
        """Create the base_dir/tag_dir output structure"""
        if not os.path.isdir(self.data_dir):
            try:
                # Create config directory only accessible to user/group running the capture
                os.makedirs(self.data_dir, mode=0o740, exist_ok=True)
                self.logger.info(f'Creating output directories')
            except OSError as exc:
                self.logger.error(f'Creating output directories: {exc.strerror}')
                sys.exit(1)

    def _loadConfig(self):
        """Load and parse the json config file"""
        self.logger.debug(f'Using config file {self.config}')
        try:
            with open(self.config, 'r') as config_stream:
                try:
                    capture_file = json.load(config_stream)
                    self._createOutputStructure()
                    return capture_file
                except json.JSONDecodeError as exc:
                    self.logger.error(
                        f'Loading config file {self.config}: JSON parse error line {exc.lineno}')
                    sys.exit(1)
        except OSError as exc:
            self.logger.error(f'Loading config file {self.config}: {exc.strerror}')
            sys.exit(1)

    def backup(self):
        """Main backup procedure to run commands and copy files"""
        self.logger.info(f'Starting system capture')
        capture_file = self._loadConfig()
        # Start by processing the direct commands
        if 'command_groups' in capture_file and len(capture_file['command_groups']) > 0:
            for group in capture_file['command_groups']:
                self.logger.debug(f'Running commands {group["exec"]}')
                write_to_file = '## ' + str(group) + '\n'
                outfile = os.path.join(self.data_dir, group['outfile'] + f'.{self.phase}')

                if ('require' in group and os.path.exists(group['require']) or
                        'require' not in group):

                    if not os.path.isfile(outfile) or self.overwrite:
                        for sub_command in group['exec']:
                            arg_list = [i for i in sub_command.split()]
                            cmd = sproc.run(arg_list, capture_output=True, encoding='UTF8')

                            if cmd.returncode == 0:
                                write_to_file += cmd.stdout + '\n'
                            else:
                                self.logger.error(f'Command exited with::{cmd.stderr}')

                            with open(outfile, 'w') as outfile_stream:
                                try:
                                    outfile_stream.write(write_to_file)
                                except OSError as exc:
                                    self.logger.error(
                                        f'Writing command to {outfile}: {exc.strerror}')
                                    sys.exit(1)
                    else:
                        self.logger.warning(
                            f'Outfile {os.path.basename(outfile)} exists and overwrite (-o) not '
                            'specified... skipping')
        else:
            self.logger.warning(f'No command groups specified in {self.config}, '
                                'skipping command capture')

        # Check if there are any files to copy
        if 'file_list' in capture_file and len(capture_file['file_list']) > 0:
            self.logger.info(f'Starting file capture')
            outfile = ''
            for infile in capture_file['file_list']:
                outfile = os.path.join(self.data_dir, os.path.basename(infile))
                if (os.path.isfile(infile) and (not os.path.isfile(outfile) or self.overwrite)):
                    try:
                        shutil.copy2(infile, f'{outfile}.{self.phase}')
                        self.logger.debug(f'Copying {infile} to {outfile}.{self.phase}')
                    except OSError as exc:
                        self.logger.error(f'Failed to copy {infile} with error {exc.strerror}')
                        sys.exit(1)
                else:
                    self.logger.warning(f'Could not capture {infile}, either source file is missing'
                                        f' or destination already exists and -o not given')
        else:
            self.logger.warning(f'No files specified in {self.config}, skipping file capture')

    @staticmethod
    def _buildFileLists(data_dir, pre_phase, post_phase):
        """Build a list of pre/post/missing files in the data directory"""
        pre_files = [os.path.splitext(i)[0] for i in glob(f'{data_dir}/*.{pre_phase}')]
        post_files = [os.path.splitext(i)[0] for i in glob(f'{data_dir}/*.{post_phase}')]

        missing_files = [file for file in pre_files if file not in post_files]
        missing_files.extend([file for file in post_files if file not in pre_files])

        return (pre_files, post_files, missing_files)

    def rundiff(self, pre_phase: str):
        """Main diff procedure to gather file list and diff against matching pre/post"""
        self.logger.info('Running diff')
        self.pre_phase = pre_phase

        pre_files, post_files, missing_files = self._buildFileLists(self.data_dir, self.pre_phase,
                                                                    self.post_phase)
        for it in missing_files:
            self.logger.warning(f'Missing phase file {it}')

        for pre_file in pre_files:
            for post_file in post_files:
                if pre_file == post_file:
                    try:
                        cmd = sproc.run(
                            ['diff', '-u', '--color=always', f'{pre_file}.{pre_phase}',
                             f'{post_file}.{self.phase}'],
                            capture_output=True,
                            encoding='UTF8')

                        if cmd.returncode == 1:
                            self.logger.warning(f'Diff found\n{cmd.stdout}')
                        elif cmd.returncode == 0:
                            self.logger.debug(f'No differences found')
                        else:
                            self.logger.error(f'Error running diff\n{cmd.stderr}')

                        break
                    except OSError as exc:
                        self.logger.error(f'Error: {exc.strerror}')
                        sys.exit(1)


def sanityCheckArgs(**args):
    return


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-b',
                        '--base-dir',
                        dest='base_dir',
                        default=os.path.expanduser('~'),
                        help='base directory for backup files')
    parser.add_argument('-c',
                        '--config',
                        dest='config',
                        default='capture.json',
                        help='supply custom config file')
    parser.add_argument('-d',
                        '--diff',
                        dest='diff_against',
                        default=False,
                        help='perform diff against this phase')
    parser.add_argument('-i',
                        '--initialise',
                        action='store_true',
                        dest='initialise',
                        default=False,
                        help='create default config file')
    parser.add_argument('-p',
                        '--phase',
                        dest='phase',
                        help='name of phase to be run')
    parser.add_argument('-t',
                        '--tag-dir',
                        dest='tag_dir',
                        default='syscap',
                        help='base directory for backup files')
    parser.add_argument('-v',
                        '--verbose',
                        dest='verbose',
                        action='store_true',
                        default=False,
                        help='enable verbose logging')
    parser.add_argument('-o',
                        '--overwrite',
                        dest='overwrite',
                        action='store_true',
                        default=False,
                        help='overwrite existing capture files')
    args = parser.parse_args()

    sanityCheckArgs(**vars(args))

    cap = SysCap(vars(args))

    if args.initialise:
        cap.initialise()
        sys.exit(0)
    if args.phase:
        cap.backup()
    if args.diff_against is not False:
        cap.rundiff(args.diff_against)

    return 0


if __name__ == '__main__':
    main()
