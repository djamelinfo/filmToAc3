import os
import subprocess
import sys
import re
from colorama import init
from colorama import Fore, Back, Style


def replace_special_characters(filename):
    return re.sub(r'\.+', ".", re.sub('[^a-zA-Z0-9\n\.]', '.', filename))


def main():
    init()
    path = sys.argv[1]
    fileFormat = "." + sys.argv[2]  # .mkv, .mp4, .avi, .mpeg, whatever.

    os.system("mkdir -p " + path + "convertedFilms")

    print("Convert no ac3 file in " + path)

    for filename in os.listdir(path):
        if os.path.isfile(path + filename) and filename.endswith(fileFormat):
            src_file = os.path.join(path, filename)
            renamed_file = os.path.join(path, replace_special_characters(filename))

            print("Rename File: '" + Fore.GREEN + src_file + Style.RESET_ALL + "'\nto :" + Fore.GREEN + renamed_file + Style.RESET_ALL)
            os.rename(src_file, renamed_file)
            output = subprocess.check_output("ffprobe -v error -show_streams {0}".format(renamed_file), shell=True)
            if "ac3" not in output.decode("utf-8"):
                print(Fore.RED + "The audio track of " + renamed_file + ", will be converted to AC3, with 5.1 channels" + Style.RESET_ALL)
                converted_file = renamed_file.replace(fileFormat, ".ac3" + fileFormat)
                print("src : " + renamed_file + "\ndist :" + converted_file)
                os.system("ffmpeg -v 1 -i " + renamed_file + " -map 0 -vcodec copy -scodec copy -acodec ac3 -b:a 640k " + converted_file)
                print("Move the converted file to " + path + "convertedFilms")
                os.system("mv " + renamed_file + " " + path + "convertedFilms/")
            else:
                continue
        else:
            continue


if __name__ == "__main__":
    main()
