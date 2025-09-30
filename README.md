# filmToAc3
Many people ask if they can convert the audio (usually DTS, DTS-HD or Dolby TrueHD) of their .mkv file to AC3 audio (Dolby Digital) without extracting the audio, converting the audio to AC3 and then muxing the audio back to .mkv.

# AC3Fixer – lightweight self-hosted AC3 converter


Small FastAPI web UI that scans a folder for video files (e.g., `.mkv`) and, when an AC3 audio track is missing, creates a new file with AC3 audio (keeping video/subtitles). Originals are moved to `convertedFilms/` to mirror your script's behavior.


## Features
- Safe renaming (sanitizes special characters like your script)
- ffprobe JSON checks for AC3 presence
- ffmpeg conversion: `-map 0 -c:v copy -c:s copy -c:a ac3 -b:a 640k -ac 6`
- Recursively scans from `MEDIA_PATH`
- One-click convert-all (background thread)


## Quick start
```bash
mkdir -p ac3fixer && cd ac3fixer
# put these files here, and your videos under ./data or bind another host path
mkdir -p data


docker compose up --build -d
# Open http://localhost:8088
```


### Configuration
Set via environment variables in `docker-compose.yml`:
- `MEDIA_PATH` (default `/data`) – bind this to your host folder
- `FILE_EXT` (default `.mkv`) – scan extension (include leading dot)
- `AUDIO_BITRATE` (default `640k`)
- `AUDIO_CHANNELS` (default `6`)


## Notes
- Converted files are created alongside the source with an extra suffix: `movie.ac3.mkv`.
- The original (renamed/sanitized) file is moved to `convertedFilms/` in the same directory after a successful conversion.
- Errors (ffprobe/ffmpeg) are shown in the UI under the Status column.
- For very large libraries or to add progress per-file, consider wiring an actual queue and SSE/WebSocket updates; this minimal app keeps things simple.