#!/usr/bin/env python
#-------------------------------------------------------------------------------------------------------
# Copyright (C) Microsoft. All rights reserved.
# Copyright (c) 2021 ChakraCore Project Contributors. All rights reserved.
# Licensed under the MIT license. See LICENSE.txt file in the project root for full license information.
#-------------------------------------------------------------------------------------------------------

# Regenerate embedded bytecode headers. This script must be run when:
# a) Ahy changes have been made to the javascript in lib/Runtime/Library/InJavascript
# b) Any changes have been made to the bytecode emission process including edits to JnDirectFields.h
# NOTEs:
# 1. this script relies on forcing 64bit CC builds to produce 32bit bytecode - this could break due to future
#    changes to CC. If this facility breaks it will need to be fixed or this script will need to be updated to
#    use 32 bit builds as well as 64 bit
# 2. Options:
#    --skip-build  Don't build CC just generate bytecode with already built binaries
#    --jit only generate bytecode for CC with jit (default is to do both jit and noJit)
#    --noJit only generate bytecode for CC with noJit (default is to do both jit and noJit)
#    --verify throw an error if bytecode changes detected - intended for use in CI
#    --binary=path provide a path to a binary to use, requires either --jit or --noJit to be set
#    --x86 specify that provided binary is an x86 build, will generate x86 bytecode only - requires pre-built binary
# 3. Python version - this script is designed to run on both Python 2.x and 3.x

import subprocess
import sys
import uuid
import os

# Parse provided parameters
verification_mode = False
skip_build = False
noJit = True
jit = True
x86 = False
overide_binary = ""

for param in sys.argv:
    if param == '--skip-build':
        skip_build = True
    elif param == '--verify':
        # welcome message for CI
        print('######### Verifying generated bytecode #########')
        verification_mode = True
    elif param == '--noJit':
        jit = False
    elif param == '--jit':
        noJit = False
    elif param == '--x86':
        x86 = True
    elif param[:9] == '--binary=':
        overide_binary = param[9:]
        skip_build = True

# Detect OS
windows = False
if os.name == 'posix':
    print('OS is Linux or macOS')
else:
    print('OS is Windows')
    windows = True

# If Jit or noJit flag has been give print a message also if both flags given revert to default behaviour
if jit == False:
    if noJit == True:
        print('Regenerating bytecode for no-jit build only')
    else:
        noJit = True
        jit = True
elif noJit == False:
    print('Regenerating bytecode for jit build only')

if x86 == True:
    if overide_binary == "":
        print('x86 build can only be used when pre-built and provided with the --binary command line parameter')
        sys.exit(1)

# Adjust path for running from different locations
base_path = os.path.abspath(os.path.dirname(__file__))

# Compile ChakraCore both noJit and Jit variants (unless disabled by args)
def run_sub(message, commands, error):
    print(message)
    sub = subprocess.Popen(commands, shell=windows)
    sub.wait()
    if sub.returncode != 0:
        print(error)
        sys.exit(1)

if skip_build == False:
    # build for linux or macOS with build.sh script - could update to use cmake directly but this works for now
    if windows == False:
        if noJit == True:
            run_sub('Compiling ChakraCore with no Jit',
                [base_path + '/../build.sh', '--no-jit', '--debug', '--static', '--target-path=' + base_path + '/../out/noJit', '-j=8'], 
                'No Jit build failed - aborting bytecode generation')
        if jit == True:
            run_sub('Compiling ChakraCore with Jit',
                [base_path + '/../build.sh', '--debug', '--static', '--target-path=' + base_path + '/../out/Jit', '-j=8'], 
                'Jit build failed - aborting bytecode generation')
    # build for windows
    else:
        if noJit == True:
            run_sub('Compiling ChakraCore with no Jit',
                ['msbuild', '/P:platform=x64', '/P:configuration=debug', '/M', '/p:BuildJIT=false', base_path+ '/../Build/Chakra.Core.sln'],
                'No Jit build failed - aborting bytecode generation')
        if jit == True:
            run_sub('Compiling ChakraCore with Jit',
                ['msbuild', '/P:platform=x64', '/P:configuration=debug', '/M', base_path + '/../Build/Chakra.Core.sln'],
                'No Jit build failed - aborting bytecode generation')


# Generate the new bytecode checking for changes to each file
# First define variables and methods that will be used then the calls take place below
changes_detected = False

# this header text will be placed at the top of the generated files
header_text = '''//-------------------------------------------------------------------------------------------------------
// Copyright (C) Microsoft. All rights reserved.
// Copyright (c) 2021 ChakraCore Project Contributors. All rights reserved.
// Licensed under the MIT license. See LICENSE.txt file in the project root for full license information.
//-------------------------------------------------------------------------------------------------------

// Generated Bytecode Header, this file was created by tools/regenByteCode.py
// This file contains:
// a) bytecode for Intl library methods implemented in javascript and
// b) bytecode for other Js library methods, JsBuiltIns, implemented in javascript

#define JsBuiltIns(VALUE)'''

def append_bytecode(header, command, in_path, file_name, error):
    command_with_file = command[:]
    command_with_file.append(in_path + file_name)
    header.write('//Bytecode generated from ' + file_name + '\nconst char Library_Bytecode_')
    header.write(file_name[:-3])
    header.flush()
    job = subprocess.Popen(command_with_file, stdout=header)
    job.wait()
    if job.returncode != 0:
        print(error)
        sys.exit(1)

# Load file and ensure line endings are '\n' if on windows
def load_file(path, mode):
    global windows
    if windows == True:
        if sys.version_info[0] < 3:
            return open(path, mode + 'b')
        else:
            return open(path, mode, newline='\n')
    else:
        return open(path, mode)

# Regenerate the bytecode
def bytecode_job(out_path, command, in_path, error):
    if verification_mode == True:
        print('Checking bytecode in file ' + out_path)
    else:
        print('Generating bytecode in file ' + out_path)

    old_version = ''
    global changes_detected
    if changes_detected == False:
        old_version = load_file(out_path, 'r').read()

    header = load_file(out_path, 'w')
    header.write(header_text)
    files = os.listdir(in_path)
    files.sort()
    filtered_files = []
    for file_name in files:
        if file_name.endswith('.js'):
            if file_name != 'Intl.js':
                without_extension = file_name[:-3]
                parts = without_extension.split('_')
                header.write(' \\\nVALUE(' + parts[0] + ', ' + parts[1] + ', ' +  parts[0] + parts[1].title() + ')')
                filtered_files.append(file_name)

    header.write('\n\nnamespace js\n{\n\n#ifdef ENABLE_JS_BUILTINS\n\n')

    # generate bytecode for JsBuiltins
    command_with_chakra_lib = command[:]
    command_with_chakra_lib.append('-LdChakraLib')
    command_with_chakra_lib.append('-JsBuiltIn')
    for file_name in filtered_files:
        append_bytecode(header, command_with_chakra_lib, in_path, file_name, error)

    # generate bytecode for Intl
    command.append('-Intl')
    header.write('#endif\n\n#ifdef ENABLE_INTL_OBJECT\n\n')
    append_bytecode(header, command, in_path, 'Intl.js', error)

    header.write('#endif\n\n}\n')
    header.close()
    if changes_detected == False:
        new_version = load_file(out_path, 'r').read()
        if new_version != old_version:
            changes_detected = True
            if verification_mode == True:
                new_lines = new_version.split('\n')
                old_lines = old_version.split('\n')
                max_lines = min(len(new_lines), len(old_lines))
                for i in range(0, max_lines):
                    if new_lines[i] != old_lines[i]:
                        print('Error found - output on line ' + str(i + 1) + ' is:')
                        print(new_lines[i].replace('\r', '\\r'))
                        print('Expected output was:')
                        print(old_lines[i].replace('\r', '\\r'))
                        break


# set paths for binaries - default paths based on build seteps above (different for windows to macOS and linux)
# OR overridden path provided on command line
noJitpath = base_path + "/../out/noJit/debug/ch"
jitPath = base_path + "/../out/jit/debug/ch"

if overide_binary != "":
    noJitpath = overide_binary
    jitPath = overide_binary
    if jit == True and noJit == True:
        print("Cannot use override binary option without specifying either jit or noJit")
        sys.exit(1)
elif windows == True:
    noJitpath = base_path + '/../Build/VcBuild.NoJIT/bin/x64_debug/ch.exe'
    jitPath = base_path + '/../Build/VcBuild/bin/x64_debug/ch.exe'

# Call the functions above to generate the bytecode
if noJit == True:
    commands = [noJitpath, '-GenerateLibraryByteCodeHeader']
    if x86 == False:
        bytecode_job(base_path + '/../lib/Runtime/Library/InJavascript/JsBuiltIn.nojit.bc.64b.h',
            commands, base_path + '/../lib/Runtime/Library/InJavascript/',
            'Failed to generate noJit 64bit Bytecode')
        commands.append('-Force32BitByteCode')

    bytecode_job(base_path + '/../lib/Runtime/Library/InJavascript/JsBuiltIn.nojit.bc.32b.h',
        commands, base_path + '/../lib/Runtime/Library/InJavascript/',
        'Failed to generate noJit 32bit JsBuiltin Bytecode')

if jit == True:
    commands = [jitPath, '-GenerateLibraryByteCodeHeader']
    if x86 == False:
        bytecode_job(base_path + '/../lib/Runtime/Library/InJavascript/JsBuiltIn.bc.64b.h',
            commands, base_path + '/../lib/Runtime/Library/InJavascript/',
            'Failed to generate 64bit JsBuiltin Bytecode')
        commands.append('-Force32BitByteCode')

    bytecode_job(base_path + '/../lib/Runtime/Library/InJavascript/JsBuiltIn.bc.32b.h',
        commands, base_path + '/../lib/Runtime/Library/InJavascript/',
        'Failed to generate 32bit JsBuiltin Bytecode')


# Bytecode regeneration complete - assess changes, report result AND if appropriate generate a new GUID
if changes_detected == True:
    if verification_mode == True:
        print('Bytecode changes detected - the generated bytecode files are not up to date please run tools/regenByteCode.py\n')
        sys.exit(1)
    if jit == False or noJit == False:
        print("Bytecode updated for one variant only - ensure you re-run for both variants before submitting code")
    else:
        print('Generating new GUID for new bytecode')
        guid_header = load_file(base_path + '/../lib/Runtime/Bytecode/ByteCodeCacheReleaseFileVersion.h', 'w')
        guid = str(uuid.uuid4())

        output_str = '''//-------------------------------------------------------------------------------------------------------
// Copyright (C) Microsoft. All rights reserved.
// Copyright (c) 2021 ChakraCore Project Contributors. All rights reserved.
// Licensed under the MIT license. See LICENSE.txt file in the project root for full license information.
//-------------------------------------------------------------------------------------------------------
// NOTE: If there is a merge conflict the correct fix is to make a new GUID.
// This file was generated with tools/regenByteCode.py

// {%s}
const GUID byteCodeCacheReleaseFileVersion =
{ 0x%s, 0x%s, 0x%s, {0x%s, 0x%s, 0x%s, 0x%s, 0x%s, 0x%s, 0x%s, 0x%s } };

''' % (guid,
            guid[:8], guid[9:13], guid[14:18], guid[19:21], guid[21:23], guid[24:26],
            guid[26:28], guid[28:30], guid[30:32], guid[32:34], guid[-2:])

        guid_header.write(output_str)

        print('Bytecode successfully regenerated. Please rebuild ChakraCore to incorporate it.')
else:
    if verification_mode == True:
        print('Bytecode is up to date\n')
    else:
        print('Bytecode update was not required')
