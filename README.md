# AC3Fixer

AC3Fixer adds an AC-3 compatibility track to an MKV for Jellyfin. Pick a DTS or
DTS-HD track, then queue the file from the web UI. FFmpeg encodes the new audio
on the CPU and stream-copies the original video, audio, subtitles, and attachments.
Chapters and metadata carry over to the new file.

## Start with Docker Compose

Run this from the repository root with a running Docker engine.

```sh
docker compose up --build -d
```

Open [http://localhost:8088](http://localhost:8088). The port is bound to localhost
by default. Docker installs FFmpeg and ffprobe in the image.

| Host directory | Container directory | Access |
| --- | --- | --- |
| `./data` | `/data` | Read-only source media |
| `./output` | `/output` | Writable converted files |

To use existing folders or a different port, put the following settings in a
`.env` file beside `docker-compose.yml` and adjust the values.

```dotenv
MEDIA_DIR=/mnt/media/movies
OUTPUT_DIR=/mnt/media/ac3fixer
AC3FIXER_PORT=8088
```

Use separate host directories and keep the output outside the source library.
The output filesystem needs hard-link support so the app can publish a verified
file atomically and keep any existing destination intact.

## Scan and convert

1. Click **Scan media** to list MKV files in the source directory and its
   subfolders. Each row shows the audio tracks and any scan error for that file.
2. Pick a DTS track in each file you want to convert. Select **Make AC-3 default**
   on a file if Jellyfin should prefer the new track. Otherwise the existing
   audio default flags are preserved. AC-3 tracks already in the source stay in
   the output alongside the new track.
3. Click **Queue selected files**. The **Conversion jobs** table updates as each
   job runs. Files with an existing destination are skipped. A failed job shows
   the error and the queue moves on to the next file.
4. Use the verified MKV from the output directory. For example,
   `./data/Films/Movie.mkv` produces `./output/Films/Movie.ac3.mkv`.

The added track keeps the selected language and is labeled **AC-3 Compatibility**.
Mono and stereo keep their channel counts. Tracks above 5.1 are downmixed to
5.1. The app runs one conversion at a time and keeps scan results and job history
in memory for the lifetime of the process.

## Published container image

GitHub Actions builds and publishes the Linux amd64 image to
`ghcr.io/djamelinfo/filmtoac3` using the repository's built-in `GITHUB_TOKEN`.
Pushes to `master` update `latest` and publish a `sha-<commit>` tag.
When a release is due, semantic-release tags that image as `vX.Y.Z` and creates
a GitHub release with generated notes. It uses Conventional Commits on
`master` to pick the version. After the first release, `feat:` bumps the minor
version, `fix:` bumps the patch, and a `BREAKING CHANGE:` footer bumps the major.

Use a Conventional Commit title when squash-merging. Pushing a version tag
manually also builds and publishes that image tag and the commit-SHA tag.

After the first successful publish, pull the image with the following command.
For a private package, authenticate first with GitHub Container Registry.
[Registry authentication](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry#authenticating-to-the-container-registry)

```sh
docker pull ghcr.io/djamelinfo/filmtoac3:latest
```

## Run the smoke tests

With Python 3.12 and `ffmpeg` and `ffprobe` on your PATH, run the following.
The tests start a local server and generate small MKVs in a temporary directory.

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```
