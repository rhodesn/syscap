#!/usr/bin/env python3

import os
import sys
import stat
import shutil
import logging
from glob import glob
import json
import argparse
import subprocess as sproc


class SysCap(object):

    def __init__(self, config, base_dir, tag_dir, phase, verbose):
        self.config = config
        self.base_dir = base_dir
        self.phase = phase
        self.verbose = verbose
        self.data_dir = os.path.join(self.base_dir, tag_dir)

        _log_level = {True: logging.DEBUG, False: logging.INFO}
        logging.basicConfig(format='%(levelname)s:%(module)s.%(funcName)s:%(message)s',
                            level=_log_level[self.verbose])
        self.logger = logging.getLogger()

    def _createOutputStructure(self):
        """ Create the base_dir/tag_dir output structure """
        if not os.path.isdir(self.data_dir):
            try:
                os.makedirs(self.data_dir, exist_ok=True)
            except OSError as exc:
                print(exc.strerror)

    def _loadConfig(self):
        """ Load and parse the json config file """
        logger = logging.getLogger()
        try:
            st = os.stat(self.config)
            # Bail if either group or other have write permissions to the capture file
            if (stat.S_IMODE(st.st_mode) & (stat.S_IWGRP | stat.S_IWOTH)):
                logger.error(f'Config file should only be writeable by owner')
                sys.exit(1)

            with open(self.config, 'r') as config_stream:
                try:
                    capture_file = json.load(config_stream)
                    self._createOutputStructure()

                    return capture_file
                except json.JSONDecodeError as exc:
                    print(exc)
        except OSError as exc:
            print(f'Encountered error {exc.strerror}')

    def backup(self):
        """ Main backup procedure to run commands and copy files """
        self.logger.info(f'Starting command capture')
        capture_file = self._loadConfig()
        # Start by processing the direct commands
        for group in capture_file['command_groups']:
            self.logger.debug(f'Running commands {group["exec"]}')
            write_to_file = '## ' + str(group) + '\n'
            outfile = os.path.join(self.data_dir, group['outfile'] + f'.{self.phase}')

            if (('require' in group and os.path.exists(group['require'])) or
                ('require' not in group)):

                for sub_command in group['exec']:
                    arg_list = [i for i in sub_command.split()]
                    cmd = sproc.run(arg_list,
                                    stdout=sproc.PIPE,
                                    stderr=sproc.STDOUT,
                                    encoding='UTF8')

                    write_to_file += cmd.stdout + '\n'

                    with open(outfile, 'w') as outfile_stream:
                        try:
                            outfile_stream.write(write_to_file)
                        except OSError as exc:
                            print(exc.strerror)
                            sys.exit(1)

        # Start the file copies
        self.logger.info(f'Starting file capture')
        outfile = ''
        for infile in capture_file['file_list']:
            if os.path.isfile(infile):
                outfile = os.path.join(self.data_dir, os.path.basename(infile))
                try:
                    shutil.copy2(infile, f'{outfile}.{self.phase}')
                    self.logger.debug(f'Copying {infile} to {outfile}.{self.phase}')
                except OSError as exc:
                    print(f'Failed to copy {infile} with error {exc.strerror}')
                    sys.exit(1)

    def rundiff(self, pre_phase):
        """ Main diff procedure to gather file list and diff against matching pre/post """
        self.logger.info('Running diff')
        self.pre_phase = pre_phase
        pre_files = [
            os.path.splitext(i)[0] for i in glob(f'{self.data_dir}/*.{pre_phase}')
        ]
        post_files = [
            os.path.splitext(i)[0] for i in glob(f'{self.data_dir}/*.{self.phase}')
        ]
        missing_pre_files = [i for i in post_files if i not in pre_files]
        missing_post_files = [i for i in pre_files if i not in post_files]

        if missing_pre_files:
            self.logger.warning(
                f'Missing {pre_phase} phase files for {", ".join(missing_pre_files)}')
        if missing_post_files:
            self.logger.warning(
                f'Missing {self.phase} phase files for {", ".join(missing_post_files)}')

        for pre_file in pre_files:
            for post_file in post_files:
                if pre_file == post_file:
                    try:
                        cmd = sproc.run([
                            'diff', '-u', '--color=always', f'{pre_file}.{pre_phase}',
                            f'{post_file}.{self.phase}'
                        ],
                                        stdout=sproc.PIPE,
                                        stderr=sproc.STDOUT,
                                        encoding='UTF8')
                        if cmd.returncode != 0:
                            self.logger.warning(f'Diff found\n{cmd.stdout}')

                        break
                    except OSError as exc:
                        print(f'Error: {exc.strerror}')
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
                        help='perform diff')
    parser.add_argument('-p',
                        '--phase',
                        dest='phase',
                        required=True,
                        help='phase being run')
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
    args = parser.parse_args()

    sanityCheckArgs(**vars(args))

    cap = SysCap(args.config, args.base_dir, args.tag_dir, args.phase, args.verbose)
    cap.backup()

    if args.diff_against is not False:
        cap.rundiff(args.diff_against)


if __name__ == '__main__':
    main()
