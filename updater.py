#!/usr/bin/env python

# Updates Drupal projects to the newest version.
# Copyright (C) 2012  Hoppinger BV
# 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

import os, sys, re, tempfile, shutil, urllib2, subprocess, difflib 
import xml.dom.minidom as minidom, mimetypes, hashlib

from pprint import pprint as p

# Make sure we are in a Drupal directory
if not os.path.isfile(os.path.join(os.getcwd(), 'modules/system/system.info')):
    print "Not in Drupal"
    sys.exit()

# Get a directory to put the patches in
print "Enter the path to place patch files is. Relative to working dir."
patches_path = False
while not patches_path:
    patches_path = raw_input("Enter: ")
patches_path = os.path.join(os.getcwd(), patches_path)
if not os.path.isdir(patches_path):
    try:
        os.makedirs(patches_path)
        print "Directory created"
    except:
        print "Creating dir failed"
        sys.exit()
else:
    print "Directory already exists. Using it."

# Information about the downloading
drupal_download_base = 'http://ftp.drupal.org/files/projects/'
drupal_download_extension = 'tar.gz'
drupal_release_info_base = 'http://updates.drupal.org/release-history/'

# Find the packages in the system
packages = []

## Some regular expressions to be able to recognize projects correctly
package_re = re.compile('^project = "(\w+)"$')
version_re = re.compile('^version = "([^"]+)"$')
core_re = re.compile('^core = "?(\d+\.x)"?$')
version_dev_re = re.compile('.*(dev|HEAD).*')
version_split_re = re.compile('^(\d+\.x-)?(\d+)\..*$')
info_re = re.compile(r"\w+\.info")
release_type_key = "Release type"
required_release_types = ["Security update"]

## Check if an info file is from a package. If so, return the package dict
def get_package(info_file):
    pkg = {}
    with open(info_file) as f:
        for line in f.readlines():
            m = package_re.match(line)
            if m:
                pkg['name'] = m.group(1)
        if not pkg.has_key('name'):
            return False

        f.seek(0)
        for line in f.readlines():
            m = version_re.match(line)
            if m:
                pkg['version'] = m.group(1)
                if version_dev_re.match(pkg['version']):
                    return False
        if not pkg.has_key('version'):
            return False

        f.seek(0)
        for line in f.readlines():
            m = core_re.match(line)
            if m:
                pkg['core'] = m.group(1)
        if not pkg.has_key('core'):
            return False

        return pkg

    return False

## Fetch Drupal core package by looking at the system module
system_pkg = get_package(os.path.join(os.getcwd(), 'modules/system/system.info'))
if system_pkg:
    system_pkg['location'] = os.getcwd()
    packages.append(system_pkg)
else:
    print "Something went wrong. System not recognized as package?"
    sys.exit()

## Walk over sites/all/modules
for root, dirs, files in os.walk(os.path.join(os.getcwd(), 'sites/all/modules')):
    try:
        dirs.remove('.svn') # do not walk into .svn dirs
    except ValueError:
        pass

    for f in files:
        if info_re.match(f):
            contrib_pkg = get_package(os.path.join(root, f))
            if contrib_pkg:
                contrib_pkg['location'] = root
                packages.append(contrib_pkg)
                dirs[:] = []
                break

# Class to use a urllib2.urlopen in a with statement. Do not use directly, but
# call the urlopen() method.
class FileURL:
    def __init__(self, url):
        self.url = url

    def __enter__(self):
        self.fp = urllib2.urlopen(self.url)
        return self.fp

    def __exit__(self, type, value, traceback):
        self.fp.close()

# Class to use a temporary directory in a with statement. The directory will be
# removed when exitting the with statement. Do not use directly, but call the
# tempdir() method.
class TempDir:
    def __enter__(self):
        self.tmpdir = tempfile.mkdtemp()
        return self.tmpdir
    def __exit__(self, type, value, traceback):
        shutil.rmtree(self.tmpdir)

# Class to use a different working directory in a with statement. Do not use 
# directly, but call the workingdir() method.
class WorkingDirectory:
    def __init__(self, wd):
        self.wd = wd
    def __enter__(self):
        self.old_wd = os.getcwd()
        os.chdir(self.wd)
        return self.wd
    def __exit__(self, type, value, traceback):
        os.chdir(self.old_wd)

# Return urllib2.urlopen() file handle wrapped in with statement compatible 
# object
def urlopen(url):
    return FileURL(url)

# Return a with statement compatible object that gives a temporary directory 
# name
def tempdir():
    return TempDir()

# Return a with statement compatible object that temporarily changes the
# working directory.
def workingdir(wd):
    return WorkingDirectory(wd)

# Walk through the package and index the existing files and directory
def construct_filelist(path, ignore_list):
    result = []
    for root, dirs, files in os.walk(path):
        # add the files that do not match with the ignore_list, to the result
        result.extend([ os.path.relpath(os.path.join(root, f), path) for f in files if not len([ True for i in ignore_list if i.match(os.path.relpath(os.path.join(root, f), path)) ]) ])
        # reduce the list of dirs to the directories that do not match with the ignore_list
        dirs[:] = [ d for d in dirs if not len([ True for i in ignore_list if i.match(os.path.relpath(os.path.join(root, d), path)) ])]
        # add the directories that remained in dirs to the result
        result.extend([ os.path.relpath(os.path.join(root, d), path) for d in dirs])

    result.sort()
    return result

# Get the first subdirectory of a path. This is because the tar.gz files from
# drupal.org are constructed to create a subdirectory, but for drupal itself the
# directory is named PACKAGE-PACKAGE_VERSION while for contrib packages it is
# named PACKAGE.
def find_download_location(path):
    for root, dirs, files in os.walk(path):
        if len(dirs) != 1:
            return False
        return os.path.join(root, dirs[0])
    return False

# Parse the major version from a version string
def extract_major(version):
    m = version_split_re.match(version)
    if m:
        return m.group(2)
    return False

# Find the latest release with the same major version
def get_best_version(package):
    major_version = extract_major(package['version'])

    url = drupal_release_info_base + package['name'] + '/' + package['core']
    with urlopen(url) as response:
        xml = response.read()

        dom = minidom.parseString(xml)
        for release in dom.getElementsByTagName('release'):
            version = ''.join([ node.data for node in release.getElementsByTagName('version')[0].childNodes if node.nodeType == node.TEXT_NODE])
            if version == package['version']:
                return version
            if ''.join([ node.data for node in release.getElementsByTagName('version_major')[0].childNodes if node.nodeType == node.TEXT_NODE]) != major_version:
                continue
            
            for term in release.getElementsByTagName('term'):
                if ''.join([ node.data for node in term.getElementsByTagName('name')[0].childNodes if node.nodeType == node.TEXT_NODE]) == release_type_key:
                    release_type = (''.join([ node.data for node in term.getElementsByTagName('value')[0].childNodes if node.nodeType == node.TEXT_NODE]))
                    if release_type in required_release_types:
                        return version
    return False

# Check if a file is binary. Bit of a trick, it scans the first Kb of the file
# for NULL bytes. GNU Diff and Git diff both work this way, but it fails with
# UTF-16 files.
def is_binary(filename):
    with open(filename, 'rb') as f:
        CHUNKSIZE = 1024
        while 1:
            chunk = f.read(CHUNKSIZE)
            if '\0' in chunk:
                return True
            if len(chunk) < CHUNKSIZE:
                break
    return False

# Construct a md5 hash for a file, without loading the whole file in memory
def md5_for_file(filename, block_size=2**20):
    md5 = hashlib.md5()

    with open(filename, 'rb') as f:
        while True:
            data = f.read(block_size)
            if not data:
                break
            md5.update(data)
    return md5.digest()

# Construct the url to download a certain version of a package from
def get_download_url(package_name, version):
    return drupal_download_base + package_name + '-' + version + '.' + drupal_download_extension

# loop over the found packages
for package in packages:
    print "\nStart analysing %s" % package['name']
    package['best_version'] = get_best_version(package)

    if package['version'] == package['best_version']:
        print "Does not need to be updated. Skip it"
        continue

    # download the package from the version that we use
    url = get_download_url(package['name'], package['version'])
    filename = package['name'] + '.' + drupal_download_extension
    with tempdir() as download_dir:
        with urlopen(url) as response:
            with open(os.path.join(download_dir, filename),'wb') as output:
                output.write(response.read())

        # extract the package
        with tempdir() as extract_dir:
            output = subprocess.check_output(['tar','-x','-C',extract_dir,'-f',os.path.join(download_dir, filename)],stderr=subprocess.STDOUT)
            if output:
                print "Extracting package failed. Skipping"
                continue

            # construct a list of regular expressions to ignore some files
            ignore_list = [
                re.compile('^(.*/)?\.svn$'), # always ignore .svn
                re.compile('^(.*/)?\.git$'), # always ignore .git
            ]
            if package['name'] == 'drupal':
                ignore_list.extend([
                    re.compile('^sites$'), # ignore sites directory
                    re.compile('^profiles/void$'), # ignore voiture void install profile
                    re.compile('^.htaccess$'), # ignore .htaccess, because it is removed for voiture projects
                    re.compile('^[A-Z]+(\.\w+)+$') # ignore ALLCAPS files in root, because we usually remove them
                ])

            # construct list of all dirs and files of existing package
            original_filelist = construct_filelist(package['location'], ignore_list)

            # construct list of all dirs and files in downloaded package
            download_location = find_download_location(extract_dir)
            if not download_location:
                print "Extracting package not found. Skipping"
                continue
            downloaded_filelist = construct_filelist(download_location, ignore_list)

            # use difflib to construct lists of matching and not matching files
            added_files = []
            removed_files = []
            matching_files = []
            d = difflib.SequenceMatcher(None, downloaded_filelist, original_filelist)
            for tag, i1, i2, j1, j2 in d.get_opcodes():
                if tag == 'insert':
                    added_files.extend(original_filelist[j1:j2])
                elif tag == 'delete':
                    removed_files.extend(downloaded_filelist[i1:i2])
                elif tag == 'replace':
                    added_files.extend(original_filelist[j1:j2])
                    removed_files.extend(downloaded_filelist[i1:i2])
                elif tag == 'equal':
                    matching_files.extend(downloaded_filelist[i1:i2])

            # loop over the files that we have in both tree
            for f in matching_files:
                # detect directories and weird stuff with directories
                if os.path.isdir(os.path.join(download_location, f)) != os.path.isdir(os.path.join(package['location'], f)):
                    print 'Problem with %s. Only one is a directory. Skipping' % f
                    continue
                elif os.path.isdir(os.path.join(download_location, f)):
                    continue

                if is_binary(os.path.join(package['location'], f)):
                    # handle binary files
                    if md5_for_file(os.path.join(download_location, f)) != md5_for_file(os.path.join(package['location'], f)):
                        if not os.path.isdir(os.path.dirname(os.path.join(patches_path, package['name'], f))):
                            os.makedirs(os.path.dirname(os.path.join(patches_path, package['name'], f)))
                        shutil.copyfile(os.path.join(package['location'], f), os.path.join(patches_path, package['name'], f))
                        print 'Diff in binary file %s. Copied to patches directory.' % f
                else:
                    # handle text files
                    output = False

                    # get diff and write to patch file if files are different
                    try:
                        subprocess.check_output([
                            'diff','-u', 
                            os.path.join(download_location, f), 
                            os.path.join(package['location'], f)
                        ],stderr=subprocess.STDOUT)
                    except subprocess.CalledProcessError as e:
                        output = e.output
                        if not os.path.isdir(os.path.dirname(os.path.join(patches_path, package['name'], f))):
                            os.makedirs(os.path.dirname(os.path.join(patches_path, package['name'], f)))
                        with open(os.path.join(patches_path, package['name'], f + '.patch'), 'w') as fp:
                            fp.write(output.replace(package['location'] + '/', '').replace(download_location + '/', ''))
                        print 'Diff in text file %s. Created patch file in patches directory.' % f

            # loop over the files that are in our tree, but not in the downloaded tree
            for f in added_files:
                if os.path.isdir(os.path.join(package['location'], f)):
                    if not os.path.isdir(os.path.join(patches_path, package['name'], f)):
                        os.makedirs(os.path.join(patches_path, package['name'], f))
                    print "Directory %s added. Created directory in patches directory." % f
                    continue

                if is_binary(os.path.join(package['location'], f)):
                    # handle binary files
                    if not os.path.isdir(os.path.dirname(os.path.join(patches_path, package['name'], f))):
                        os.makedirs(os.path.dirname(os.path.join(patches_path, package['name'], f)))
                    shutil.copyfile(os.path.join(package['location'], f), os.path.join(patches_path, package['name'], f))
                    print 'Added binary file %s. Copied to patches directory.' % f
                else:
                    # handle text files
                    output = False

                    # get diff and write to patch file if files are different
                    try:
                        subprocess.check_output([
                            'diff','-uN', 
                            os.path.join(download_location, f), # we need a location that we kwow is non-existant
                            os.path.join(package['location'], f)
                        ],stderr=subprocess.STDOUT)
                    except subprocess.CalledProcessError as e:
                        output = e.output
                        if not os.path.isdir(os.path.dirname(os.path.join(patches_path, package['name'], f))):
                            os.makedirs(os.path.dirname(os.path.join(patches_path, package['name'], f)))
                        with open(os.path.join(patches_path, package['name'], f + '.patch'), 'w') as fp:
                            fp.write(output.replace(package['location'] + '/', '').replace(download_location + '/', ''))
                        print 'Added text file %s. Created patch file in patches directory.' % f

            # loop over the files that are in the downloaded tree, but not in our tree
            for f in removed_files:
                if os.path.isdir(os.path.join(download_location, f)):
                    print "Directory %s is removed. Ignoring" % f
                    continue

                if is_binary(os.path.join(download_location, f)):
                    # handle binary files
                    if not os.path.isdir(os.path.dirname(os.path.join(patches_path, package['name'], f))):
                        os.makedirs(os.path.dirname(os.path.join(patches_path, package['name'], f)))
                    shutil.copyfile(os.path.join(download_location, f), os.path.join(patches_path, package['name'], f + '.remove'))
                    print 'Removed binary file %s. Copied to patches directory with a .remove suffix.' % f
                else:
                    # handle text files
                    output = False

                    # get diff and write to patch file if files are different
                    try:
                        subprocess.check_output([
                            'diff','-uN', 
                            os.path.join(download_location, f),
                            os.path.join(package['location'], f) # we need a location that we kwow is non-existant
                        ],stderr=subprocess.STDOUT)
                    except subprocess.CalledProcessError as e:
                        output = e.output
                        if not os.path.isdir(os.path.dirname(os.path.join(patches_path, package['name'], f))):
                            os.makedirs(os.path.dirname(os.path.join(patches_path, package['name'], f)))
                        with open(os.path.join(patches_path, package['name'], f + '.patch'), 'w') as fp:
                            fp.write(output.replace(package['location'] + '/', '').replace(download_location + '/', ''))
                        print 'Removed text file %s. Created patch file in patches directory.' % f

            print "Updating package"

            # download the package from the best version
            best_url = get_download_url(package['name'], package['best_version'])
            with tempdir() as best_download_dir:
                with urlopen(best_url) as response:
                    with open(os.path.join(best_download_dir, filename),'wb') as output:
                        output.write(response.read())

                # extract the package
                with tempdir() as best_extract_dir:
                    output = subprocess.check_output(['tar','-x','-C',best_extract_dir,'-f',os.path.join(best_download_dir, filename)],stderr=subprocess.STDOUT)
                    if output:
                        print "Extracting package failed. Skipping"
                        continue

                    # construct list of all dirs and files in downloaded package
                    best_download_location = find_download_location(best_extract_dir)
                    if not best_download_location:
                        print "Extracting package not found. Skipping"
                        continue
                    best_downloaded_filelist = construct_filelist(best_download_location, ignore_list)

                    # check if we need to remove files or directories
                    for f in original_filelist:
                        if os.path.isdir(os.path.join(package['location'], f)) and not os.path.isdir(os.path.join(best_download_location, f)):
                            shutil.rmtree(os.path.join(package['location'], f))
                            print "Directory %s removed" % f
                        if os.path.isfile(os.path.join(package['location'], f)) and not os.path.isfile(os.path.join(best_download_location, f)):
                            os.remove(os.path.join(package['location'], f))
                            print "File %s removed" % f

                    # copy new files and directories into the project
                    for f in best_downloaded_filelist:
                        if os.path.isdir(os.path.join(best_download_location, f)):
                            if not os.path.isdir(os.path.join(package['location'], f)):
                                os.makedirs(os.path.join(package['location'], f))
                        else:
                            shutil.copyfile(os.path.join(best_download_location, f), os.path.join(package['location'], f))

                    # loop over the files that we have in both tree
                    for f in matching_files:
                        if os.path.isfile(os.path.join(patches_path, package['name'], f)) and is_binary(os.path.join(patches_path, package['name'], f)):
                            shutil.copyfile(os.path.join(patches_path, package['name'], f), os.path.join(package['location'], f))
                            print "Copied changed binary file %s back into the project" % f
                        if os.path.isfile(os.path.join(patches_path, package['name'], f + '.patch')):
                            with workingdir(package['location']):
                                with open(os.path.join(patches_path, package['name'], f + '.patch')) as fp:
                                    try:
                                        output = subprocess.check_output(['patch', '-f', '-p0'], stderr = subprocess.STDOUT, stdin = fp)
                                        print output
                                    except subprocess.CalledProcessError as e:
                                        print e.output
                    for f in added_files:
                        if os.path.isfile(os.path.join(patches_path, package['name'], f)) and is_binary(os.path.join(patches_path, package['name'], f)):
                            if not os.path.isdir(os.path.dirname(os.path.join(package['location'], f))):
                                os.makedirs(os.path.dirname(os.path.join(package['location'], f)))
                            shutil.copyfile(os.path.join(patches_path, package['name'], f), os.path.join(package['location'], f))
                            print "Copied added binary file %s back into the project" % f
                        if os.path.isfile(os.path.join(patches_path, package['name'], f + '.patch')):
                            with workingdir(package['location']):
                                with open(os.path.join(patches_path, package['name'], f + '.patch')) as fp:
                                    try:
                                        output = subprocess.check_output(['patch', '-f', '-p0'], stderr = subprocess.STDOUT, stdin = fp)
                                        print output
                                    except subprocess.CalledProcessError as e:
                                        print e.output
                    for f in removed_files:
                        if os.path.isdir(os.path.join(package['location'], f)):
                            shutil.rmtree(os.path.join(package['location'], f))
                            print "Removed directory %s" % f
                        elif os.path.isfile(os.path.join(package['location'], f)):
                            os.remove(os.path.join(package['location'], f))
                            print "Removed file %s" % f
