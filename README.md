# Drupal Updater

Python script that can update both core and contrib modules in a Drupal 
installation. It also is able to find core and contrib patches and reapply them
to the updated core and modules.

We are, of course, perfectly aware of the fact that you're 
[not supposed to hack core](http://www.flickr.com/photos/hagengraf/2802915470/),
nor contrib modules. However, in reality, Drupal sometimes doesn't leave you 
much choice. One of the most painful consequences of hacking core or contrib is
that updating becomes a major pain. Even if you employ a policy of documenting
all core and contrib patches, you still can't be 100% sure that all patches are
actually documented. That's were this handy script comes in. It detects the
patches that are made in the project, stores them somewhere and reapplies the
patches after updating.

## Usage

The script should be executed from within the Drupal installation root.

    cd /path/to/drupal
    /path/to/updater.py 

It will ask for a directory to store the found core and contrib patches in. In a
Voiture enabled we usally use `../dev/patches` or something similar. After you 
entered a directory it will start the process of updating. 

It will output quite a lot of information. Please read the 'What does it do' 
section thoroughly to understand all output. Pay special attention to output
that indicates a failure while applying a patch. These errors will require some
manual labor to fix.

**This tool is not limited to Voiture projects. It should work perfectly fine in
any Drupal installation.**

## What does it do?

It searches for `*.info` files in your Drupal installation. Based on these files
it builds a list of packages (excluding the `*-dev` versions) that are 
downloaded from drupal.org.

It then starts looping over these packages. First, the latest version with the
same major version number of the package is determined. If you already run the
latest version, it directly continues to the next package.

If the package needs updating, the version of the package that you are running 
now is downloaded from drupal.org and compared to the package that is in your 
project. If differences are found, patches are written to the folder that is 
indicated as patch destination. Then, the latest version of the package is
downloaded and extracted over the package in your project. It then starts to try
to re-apply the patches. 

This is the most tricky part. Sometimes reapplying the patches works out
perfectly fine. Sometimes you patched to fix a bug that is now also fixed in the
official project and the patch will fail. Sometimes you simply patched a part
that is now changed in the original project. If the `patch`  command returns
output, the script will display this output. Pay special attention to these
outputs. It can mean that the patch is still applied fine, but can also indicate
failure. 

## Assumptions

* Contrib modules are placed somewhere in `sites/all/modules`. We usually place
  them in `sites/all/modules/contrib`.
* Python 2.7.x. We did not test this on any other Python version. However, 2.6.x
  probably will work, 3.x probably won't.

## License

Copyright &copy; 2012  Hoppinger BV

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see &lt;<http://www.gnu.org/licenses/>&gt;.
