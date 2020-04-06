import os
import subprocess
import sys

path = sys.argv[1]
fileFormat = "."+sys.argv[2]  # .mkv, .mp4, .avi, .mpeg, whatever.

os.system("mkdir -p " + path + "convertedFilms")

for filename in os.listdir(path):

    print("List of no ac3 file in " + path)

    if os.path.isfile(path + filename) & filename.endswith(fileFormat):
        # print(filename)
        output = subprocess.check_output("ffprobe -v error -show_streams " + path + "{0}".format(filename),shell=True)
        if "ac3" not in output.decode("utf-8"):
            print(output)
            distFileName = filename.replace(fileFormat, ".ac3"+fileFormat)
            print("src : " + filename + "\ndist :" + distFileName)
            os.system("ffmpeg -v 1 -i " + path + filename + " -map 0 -vcodec copy -scodec copy -acodec ac3 -b:a 640k " + path + distFileName)
            print("move file to " + path + "convertedFilms")
            os.system("mv " + path + filename + " " + path + "convertedFilms/")
        else:
            continue
    else:
        continue
    