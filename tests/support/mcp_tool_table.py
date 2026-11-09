"""The table of a person's agent tools: each tool, the route it calls and its arguments.

``test_mcp_person_tools`` and ``test_mcp_person_lifecycle_tools`` drive every row through the
real app; ``mcp_world`` seeds the two people the rows name.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

ALICE = "alices"
BOB = "bobs"

Arguments = Callable[[str, str], dict]


@dataclass(frozen=True)
class Tool:
    """A tool, the route it calls and its arguments for a resource owner and a second one.

    ``subject`` names the owner of the container or the thing acted on, ``other`` the owner of
    what is added to it; a case with one resource uses ``subject`` only.
    """

    name: str
    method: str
    template: str
    arguments: Arguments = lambda subject, other: {}  # noqa: ARG005
    crossed: bool = False

    def arguments_for(self, subject: str, other: str | None = None) -> dict:
        return self.arguments(subject, other or subject)

    def request(self, subject: str) -> tuple[str, dict]:
        """The browser's path and the arguments left for its body or query."""
        arguments = self.arguments_for(subject)
        path = self.template.format(**arguments)
        left = {k: v for k, v in arguments.items() if "{" + k + "}" not in self.template}
        return path, left

    @property
    def refused_pairs(self) -> list[tuple[str, str]]:
        return [(BOB, BOB), (ALICE, BOB), (BOB, ALICE)] if self.crossed else [(BOB, BOB)]


def _take_arguments(subject: str, other: str) -> dict:
    return {"gen_id": f"take-{subject}"}


def _cover_arguments(subject: str, other: str) -> dict:
    return {"gen_id": f"take-{subject}", "src_generation_id": f"take-{subject}", "model": "sft"}


def repaint_arguments(subject: str, other: str) -> dict:
    return {**_cover_arguments(subject, other), "repainting_start": 0.1, "repainting_end": 0.5}


# Reads of one resource of a person: a stranger's gets the browser's refusal.
READS_OF_ONE_RESOURCE = [
    Tool("get_album", "GET", "/api/albums/{album_id}", lambda s, o: {"album_id": f"album-{s}"}),
    Tool("list_cover_suggestions", "GET", "/api/albums/{album_id}/cover-suggestions",
         lambda s, o: {"album_id": f"album-{s}"}),
    Tool("get_take", "GET", "/api/generations/{gen_id}", _take_arguments),
    Tool("get_lora", "GET", "/api/loras/{lora_id}", lambda s, o: {"lora_id": f"lora-{s}"}),
    Tool("get_job", "GET", "/api/jobs/{job_id}", lambda s, o: {"job_id": f"job-{s}"}),
    Tool("get_playlist", "GET", "/api/playlists/{playlist_id}",
         lambda s, o: {"playlist_id": f"playlist-{s}"}),
    Tool("list_reference_uses", "GET", "/api/references/{reference_id}/uses",
         lambda s, o: {"reference_id": f"reference-{s}"}),
    Tool("list_song_versions", "GET", "/api/songs/{song_id}/versions",
         lambda s, o: {"song_id": f"song-{s}"}),
]

# Reads of what a person has as a list, or of what every member sees.
PLAIN_READS = [
    Tool("get_account", "GET", "/api/auth/me"),
    Tool("get_library_listen", "GET", "/api/library/listen"),
    Tool("get_library_write", "GET", "/api/library/write"),
    Tool("search_library", "GET", "/api/library/search", lambda s, o: {"q": "Song"}),
    Tool("get_library_pool_queue", "GET", "/api/library/pool-queue"),
    Tool("list_loras", "GET", "/api/loras"),
    Tool("list_own_playable_takes", "GET", "/api/own-playable-takes"),
    Tool("list_playlists", "GET", "/api/playlists"),
    Tool("list_references", "GET", "/api/references"),
    Tool("get_release", "GET", "/api/release"),
    Tool("get_cowriter_settings", "GET", "/api/settings/cowriter"),
    Tool("get_default_config", "GET", "/api/settings/default-config"),
    Tool("get_generation_builtins", "GET", "/api/settings/generation-builtins"),
    Tool("get_generation_defaults", "GET", "/api/settings/generation-defaults"),
    Tool("list_models", "GET", "/api/settings/models"),
    Tool("list_presets", "GET", "/api/settings/presets"),
    Tool("get_theme", "GET", "/api/settings/theme"),
]

# Writes on a resource of a person: a stranger's is refused and nothing is written.
WRITES_ON_ONE_RESOURCE = [
    Tool("archive_album", "POST", "/api/albums/{album_id}/archive",
         lambda s, o: {"album_id": f"album-{s}"}),
    Tool("unarchive_album", "POST", "/api/albums/{album_id}/unarchive",
         lambda s, o: {"album_id": f"album-{s}"}),
    Tool("restore_album", "POST", "/api/albums/{album_id}/restore",
         lambda s, o: {"album_id": f"album-gone-{s}"}),
    Tool("restore_song", "POST", "/api/songs/{song_id}/restore",
         lambda s, o: {"song_id": f"song-gone-{s}"}),
    Tool("keep_take", "POST", "/api/generations/{gen_id}/keep", _take_arguments),
    Tool("unarchive_take", "POST", "/api/generations/{gen_id}/unarchive", _take_arguments),
    Tool("rate_take", "POST", "/api/generations/{gen_id}/rate",
         lambda s, o: {**_take_arguments(s, o), "rating": 80}),
    Tool("score_take", "POST", "/api/generations/{gen_id}/score", _take_arguments),
    Tool("cover_take", "POST", "/api/generations/{gen_id}/cover", _cover_arguments),
    Tool("repaint_take", "POST", "/api/generations/{gen_id}/repaint", repaint_arguments),
    Tool("cancel_job", "POST", "/api/jobs/{job_id}/cancel", lambda s, o: {"job_id": f"job-{s}"}),
    Tool("keep_reference", "POST", "/api/references/{reference_id}/keep",
         lambda s, o: {"reference_id": f"reference-{s}"}),
    Tool("set_default_preset", "POST", "/api/settings/presets/{preset_id}/set-default",
         lambda s, o: {"preset_id": f"preset-{s}"}),
    Tool("add_lora_sample_from_take", "POST", "/api/loras/{lora_id}/samples/from-generation",
         lambda s, o: {"lora_id": f"lora-{s}", "generation_id": f"take-{o}"}, crossed=True),
    Tool("add_album_to_playlist", "POST", "/api/playlists/{playlist_id}/entries/album",
         lambda s, o: {"playlist_id": f"playlist-{s}", "album_id": f"album-{o}"}, crossed=True),
    Tool("add_take_to_playlist", "POST", "/api/playlists/{playlist_id}/entries/generation",
         lambda s, o: {"playlist_id": f"playlist-{s}", "generation_id": f"take-{o}"},
         crossed=True),
    Tool("add_song_to_playlist", "POST", "/api/playlists/{playlist_id}/entries/song",
         lambda s, o: {"playlist_id": f"playlist-{s}", "song_id": f"song-{o}"}, crossed=True),
    Tool("update_album", "PUT", "/api/albums/{album_id}",
         lambda s, o: {"album_id": f"album-{s}", "title": "Renamed album"}),
    Tool("update_playlist", "PUT", "/api/playlists/{playlist_id}",
         lambda s, o: {"playlist_id": f"playlist-{s}", "title": "Renamed list"}),
    Tool("move_playlist_entry", "PATCH", "/api/playlists/{playlist_id}/entries/{entry_id}/position",
         lambda s, o: {"playlist_id": f"playlist-filled-{s}", "entry_id": f"entry-{s}",
                       "new_position": 1}),
    Tool("remove_playlist_entry", "DELETE", "/api/playlists/{playlist_id}/entries/{entry_id}",
         lambda s, o: {"playlist_id": f"playlist-filled-{s}", "entry_id": f"entry-{s}-extra"}),
    Tool("update_preset", "PUT", "/api/settings/presets/{preset_id}",
         lambda s, o: {"preset_id": f"preset-{s}", "name": "Renamed preset"}),
    Tool("rename_song", "PUT", "/api/songs/{song_id}/title",
         lambda s, o: {"song_id": f"song-{s}", "title": "Renamed song"}),
    Tool("move_song", "PUT", "/api/songs/{song_id}/album",
         lambda s, o: {"song_id": f"song-{s}", "album_id": f"album-{o}"}, crossed=True),
    Tool("update_lora_sample", "PATCH", "/api/loras/{lora_id}/samples/{sample_id}",
         lambda s, o: {"lora_id": f"lora-{s}", "sample_id": f"sample-{s}-0",
                       "caption": "new caption"}),
    Tool("write_song_memory", "PUT", "/api/memory/songs/{song_id}",
         lambda s, o: {"song_id": f"song-{s}", "body": "a note"}),
    Tool("write_album_memory", "PUT", "/api/memory/albums/{album_id}",
         lambda s, o: {"album_id": f"album-{s}", "body": "a note"}),
]

# Writes that make something new for the person.
CREATIONS = [
    Tool("create_lora", "POST", "/api/loras", lambda s, o: {"name": "Fresh voice"}),
    Tool("create_playlist", "POST", "/api/playlists", lambda s, o: {"title": "Fresh list"}),
    Tool("create_preset", "POST", "/api/settings/presets",
         lambda s, o: {"name": "Fresh preset", "model_mode": "sft", "params": {}}),
    Tool("set_theme", "PUT", "/api/settings/theme", lambda s, o: {"theme": "dark"}),
    Tool("set_default_config", "PUT", "/api/settings/default-config",
         lambda s, o: {"config": f"preset-{s}"}),
    Tool("write_user_memory", "PUT", "/api/memory/user", lambda s, o: {"body": "a note"}),
]

ALL_TOOLS = [*READS_OF_ONE_RESOURCE, *PLAIN_READS, *WRITES_ON_ONE_RESOURCE, *CREATIONS]
