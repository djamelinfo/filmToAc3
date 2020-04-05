import os
import subprocess
import sys

path = sys.argv[1]
fileFormat = "."+sys.argv[2]
print("List of no ac3 file in " + path)
os.system("mkdir -p " + path + "convertedFilms")
for filename in os.listdir(path):
    # print(os.path.isfile(path+filename))
    if filename.endswith(fileFormat):
        if os.path.isfile(path + filename):
            # print(filename)
            output = subprocess.check_output("ffprobe -v error -show_streams " + path + "{0}".format(filename),shell=True)
            if "ac3" not in output.decode("utf-8"):  # or .avi, .mpeg, whatever.
                print(output)
                distFileName = filename.replace(fileFormat, ".ac3.")
                print("src : " + filename + "\ndist :" + distFileName)
                # ffmpeg -i /mnt/c/films/Kubo_And_The_Two_Strings_2016_1080p.mkv -map 0 -vcodec copy -scodec copy -acodec ac3 -b:a 640k film_ac3.mkv
                os.system("ffmpeg -i " + path + filename + " -map 0 -vcodec copy -scodec copy -acodec ac3 -b:a 640k " + path + distFileName)
                print("move file to " + path + "convertedFilms")
                os.system("mv " + path + filename + " " + path + "convertedFilms/")
            else:
                continue
        else:
            continue
    else:
        continue