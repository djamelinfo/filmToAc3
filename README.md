# AC3Fixer

AC3Fixer adds an AC-3 compatibility track to an MKV for Jellyfin. Pick a DTS or
DTS-HD track, then queue the file from the web UI. FFmpeg encodes the new audio
on the CPU and stream-copies the original video, audio, subtitles, and attachments.
Chapters and metadata carry over to the new file.

## Start with Docker Compose

From the repository root, start Compose with a running Docker engine. Compose
pulls the published Linux amd64 image from GitHub Container Registry.

```sh
docker compose up -d
```

Open [http://localhost:8088](http://localhost:8088). The port is bound to localhost
by default. The published image includes FFmpeg and ffprobe.

| Host directory | Container directory | Access |
| --- | --- | --- |
| `./data` | `/data` | Source media, read-only by default |
| `./output` | `/output` | Writable converted files |

To use existing folders or a different port, put the following settings in a
`.env` file beside `docker-compose.yml` and adjust the values.

```dotenv
MEDIA_DIR=/mnt/media/movies
OUTPUT_DIR=/mnt/media/ac3fixer
AC3FIXER_PORT=8088
SCAN_WORKERS=2
```

Use separate host directories and keep the output outside the source library.
For example, set `MEDIA_DIR=/media/media/Films` and
`OUTPUT_DIR=/media/media/downloads/Films` for those folders on the Docker host.
The app uses the container paths `/data` and `/output`.
The output filesystem needs hard-link support so the app can publish a verified
file atomically and keep any existing destination intact.

## Scan and convert

1. Click **Scan media** to inspect MKVs in the source directory and its
   subfolders. **Files to convert** shows MKVs with a DTS or DTS-HD track that
   still need an output. Scan errors appear separately.
2. Pick a DTS track in each file you want to convert. Select **Make AC-3 default**
   on a file if Jellyfin should prefer the new track. Otherwise the existing
   audio default flags are preserved. AC-3 tracks already in the source stay in
   the output alongside the new track.
3. Click **Queue selected files**. The **Conversion jobs** table updates as each
   job runs. The progress bar estimates completion from the source duration when
   available. A job is completed after AC3Fixer verifies and publishes the output.
   Files with an existing destination are skipped. A failed job shows the error
   and the queue moves on to the next file.
4. Use the verified MKV from the output directory. For example,
   `./data/Films/Movie.mkv` produces `./output/Films/Movie.ac3.mkv`.

The conversion list updates when files enter the queue or finish. Failed files
that can be retried return to the list.

AC3Fixer probes up to two MKVs at a time. Set `SCAN_WORKERS=1` to limit scanning
to one probe at a time on a busy network share. Repeat scans reuse audio metadata
for unchanged files and probe new or changed files. The cache lasts until the
app restarts.

The dashboard shows source MKVs found by the latest scan, files needing attention,
completed outputs, and queued or running conversions. DTS candidates awaiting
conversion, scan errors, and failed conversions appear in **Needs attention**.

The added track keeps the selected language and is labeled **AC-3 Compatibility**.
Mono and stereo keep their channel counts. Tracks above 5.1 are downmixed to
5.1. The app runs one conversion at a time and keeps scan results and job history
in memory for the lifetime of the process.

## Move a converted film or delete its original

To enable these two buttons, set `MEDIA_READ_ONLY=false` in your Compose
`.env` and run `docker compose up -d`. This setting gives the container write
access to the source mount and enables the actions in the app. If you maintain
your own Compose file, pass `MEDIA_READ_ONLY: "false"` in the service environment
and make the `/data` bind mount writable. Anyone who can access that UI can use
the enabled file actions. Scanning only reads files in either mode.

Click **Scan media**, then open **Manage converted films**. Each action applies
to one film. The table uses `/data/Films/Movie.mkv` as an example.

| Action | Result |
| --- | --- |
| **Move output to library** | Moves `/output/Films/Movie.ac3.mkv` to `/data/Films/Movie.ac3.mkv`. The original stays beside it. |
| **Delete original** | Asks you to confirm `Films/Movie.mkv`. After verification, removes that original and keeps the converted film in its current folder. |

The move progress bar appears beside the film. On separate mounts, the first
half tracks bytes copied and the second half tracks bytes verified. The bar
shows activity during the initial film check and reaches 100% after the staged
file is removed. Refreshing the page shows the current move. A same-filesystem
move can finish immediately using a hard link.

You can use either action first. After a restart, a scan finds staged
`.ac3.mkv` files even if their originals have been deleted. Moves across mounts
use a temporary copy and compare its contents before publishing. The library
filesystem needs hard-link support for publication. A different file already at
the destination is kept and the move reports the conflict.

Before deleting, AC3Fixer reads both films to compare the original stream data,
including attachments, and checks the added AC-3 track. This can take time over
SMB. AC3Fixer also uses this comparison when moving an output from an older
release. These checks run when you use the buttons.

New outputs carry the Matroska tag `AC3FIXER_PROCESSED=1`. Scans ignore them
even after renaming. For older `.ac3.mkv` files, the scanner recognizes a final
AC-3 track titled **AC-3 Compatibility** that matches a DTS track's language
and expected channel count. When the
converted file is beside its original under the expected name, the original
also stays off the conversion list.

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

Compose uses `latest` by default. To pin a published release, set
`AC3FIXER_TAG` to its version tag in `.env`. To update the local service, run
`docker compose pull ac3fixer` followed by `docker compose up -d ac3fixer`.
For a private package, authenticate first with GitHub Container Registry.
[Registry authentication](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry#authenticating-to-the-container-registry)

## Run locally with uv

Install uv and put `ffmpeg` and `ffprobe` on your PATH. From the repository
root, install the same locked dependencies as the Docker image and run the tests.
The tests start a local server and generate small MKVs in a temporary directory.

```sh
uv sync --locked --python 3.12
uv run --locked python -m unittest discover -s tests -v
```

To start the web UI locally, set `MEDIA_PATH` and `OUTPUT_PATH` to your source
and output directories, then run `uv run --locked uvicorn app.main:app --port 8088`.
