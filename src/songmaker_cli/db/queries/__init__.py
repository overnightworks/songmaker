"""Database query functions — split by domain, re-exported here for compatibility."""

from songmaker_cli.db.queries.albums import RestoreWindowExpiredError as RestoreWindowExpiredError
from songmaker_cli.db.queries.albums import cleanup_album as cleanup_album
from songmaker_cli.db.queries.albums import count_albums as count_albums
from songmaker_cli.db.queries.albums import create_album as create_album
from songmaker_cli.db.queries.albums import delete_album as delete_album
from songmaker_cli.db.queries.albums import disable_album_sharing as disable_album_sharing
from songmaker_cli.db.queries.albums import enable_album_sharing as enable_album_sharing
from songmaker_cli.db.queries.albums import get_album as get_album
from songmaker_cli.db.queries.albums import get_album_by_slug as get_album_by_slug
from songmaker_cli.db.queries.albums import list_albums as list_albums
from songmaker_cli.db.queries.albums import list_expired_albums as list_expired_albums
from songmaker_cli.db.queries.albums import restore_album as restore_album
from songmaker_cli.db.queries.albums import soft_delete_album as soft_delete_album
from songmaker_cli.db.queries.auth import (
    LOGIN_ATTEMPT_RETENTION_DAYS as LOGIN_ATTEMPT_RETENTION_DAYS,
)
from songmaker_cli.db.queries.auth import (
    cleanup_old_login_attempts as cleanup_old_login_attempts,
)
from songmaker_cli.db.queries.auth import count_active_sessions as count_active_sessions
from songmaker_cli.db.queries.auth import count_audit_log as count_audit_log
from songmaker_cli.db.queries.auth import count_login_attempts as count_login_attempts
from songmaker_cli.db.queries.auth import (
    count_recent_failed_attempts as count_recent_failed_attempts,
)
from songmaker_cli.db.queries.auth import create_session as create_session
from songmaker_cli.db.queries.auth import create_user as create_user
from songmaker_cli.db.queries.auth import delete_expired_sessions as delete_expired_sessions
from songmaker_cli.db.queries.auth import delete_session as delete_session
from songmaker_cli.db.queries.auth import delete_user_sessions as delete_user_sessions
from songmaker_cli.db.queries.auth import get_session_with_user as get_session_with_user
from songmaker_cli.db.queries.auth import get_user as get_user
from songmaker_cli.db.queries.auth import get_user_by_username as get_user_by_username
from songmaker_cli.db.queries.auth import hard_delete_user as hard_delete_user
from songmaker_cli.db.queries.auth import list_active_sessions as list_active_sessions
from songmaker_cli.db.queries.auth import list_audit_log as list_audit_log
from songmaker_cli.db.queries.auth import list_login_attempts as list_login_attempts
from songmaker_cli.db.queries.auth import list_users as list_users
from songmaker_cli.db.queries.auth import record_audit as record_audit
from songmaker_cli.db.queries.auth import record_login_attempt as record_login_attempt
from songmaker_cli.db.queries.auth import update_user as update_user
from songmaker_cli.db.queries.auth import user_count as user_count
from songmaker_cli.db.queries.chat import count_chat_messages as count_chat_messages
from songmaker_cli.db.queries.chat import create_chat_message as create_chat_message
from songmaker_cli.db.queries.chat import delete_chat_messages as delete_chat_messages
from songmaker_cli.db.queries.chat import list_chat_messages as list_chat_messages
from songmaker_cli.db.queries.chat import songs_with_chat as songs_with_chat
from songmaker_cli.db.queries.generations import (
    all_generation_paths as all_generation_paths,
)
from songmaker_cli.db.queries.generations import (
    bulk_delete_generations as bulk_delete_generations,
)
from songmaker_cli.db.queries.generations import create_generation as create_generation
from songmaker_cli.db.queries.generations import delete_generation as delete_generation
from songmaker_cli.db.queries.generations import (
    delete_generation_files as delete_generation_files,
)
from songmaker_cli.db.queries.generations import (
    disable_generation_sharing as disable_generation_sharing,
)
from songmaker_cli.db.queries.generations import (
    enable_generation_sharing as enable_generation_sharing,
)
from songmaker_cli.db.queries.generations import get_generation as get_generation
from songmaker_cli.db.queries.generations import (
    get_generation_by_slug as get_generation_by_slug,
)
from songmaker_cli.db.queries.generations import keep_generation as keep_generation
from songmaker_cli.db.queries.generations import pick_generation as pick_generation
from songmaker_cli.db.queries.generations import save_rating as save_rating
from songmaker_cli.db.queries.generations import save_scores as save_scores
from songmaker_cli.db.queries.generations import unkeep_generation as unkeep_generation
from songmaker_cli.db.queries.generations import unpick_generation as unpick_generation
from songmaker_cli.db.queries.jobs import JobDurationStats as JobDurationStats
from songmaker_cli.db.queries.jobs import clear_stale_user_jobs as clear_stale_user_jobs
from songmaker_cli.db.queries.jobs import count_total_queued_jobs as count_total_queued_jobs
from songmaker_cli.db.queries.jobs import count_user_active_jobs as count_user_active_jobs
from songmaker_cli.db.queries.jobs import (
    count_user_jobs_in_window as count_user_jobs_in_window,
)
from songmaker_cli.db.queries.jobs import create_job as create_job
from songmaker_cli.db.queries.jobs import get_job as get_job
from songmaker_cli.db.queries.jobs import get_queue_position as get_queue_position
from songmaker_cli.db.queries.jobs import has_active_job_of_type as has_active_job_of_type
from songmaker_cli.db.queries.jobs import (
    job_counts_by_type_and_status as job_counts_by_type_and_status,
)
from songmaker_cli.db.queries.jobs import job_duration_stats as job_duration_stats
from songmaker_cli.db.queries.jobs import recover_stale_jobs as recover_stale_jobs
from songmaker_cli.db.queries.jobs import recover_stale_jobs_by_age as recover_stale_jobs_by_age
from songmaker_cli.db.queries.jobs import (
    recover_stale_jobs_by_age_and_type as recover_stale_jobs_by_age_and_type,
)
from songmaker_cli.db.queries.jobs import (
    recover_stale_jobs_by_type as recover_stale_jobs_by_type,
)
from songmaker_cli.db.queries.jobs import update_job_heartbeat as update_job_heartbeat
from songmaker_cli.db.queries.jobs import update_job_status as update_job_status
from songmaker_cli.db.queries.playlists import (
    add_album_to_playlist as add_album_to_playlist,
)
from songmaker_cli.db.queries.playlists import (
    add_generation_to_playlist as add_generation_to_playlist,
)
from songmaker_cli.db.queries.playlists import add_song_to_playlist as add_song_to_playlist
from songmaker_cli.db.queries.playlists import create_playlist as create_playlist
from songmaker_cli.db.queries.playlists import delete_playlist as delete_playlist
from songmaker_cli.db.queries.playlists import (
    disable_playlist_sharing as disable_playlist_sharing,
)
from songmaker_cli.db.queries.playlists import (
    enable_playlist_sharing as enable_playlist_sharing,
)
from songmaker_cli.db.queries.playlists import get_playlist as get_playlist
from songmaker_cli.db.queries.playlists import get_playlist_by_slug as get_playlist_by_slug
from songmaker_cli.db.queries.playlists import list_playlists as list_playlists
from songmaker_cli.db.queries.playlists import remove_from_playlist as remove_from_playlist
from songmaker_cli.db.queries.playlists import (
    reorder_playlist_entry as reorder_playlist_entry,
)
from songmaker_cli.db.queries.playlists import update_playlist as update_playlist
from songmaker_cli.db.queries.rate_limits import (
    delete_all_user_rate_limits as delete_all_user_rate_limits,
)
from songmaker_cli.db.queries.rate_limits import (
    delete_rate_limit_setting as delete_rate_limit_setting,
)
from songmaker_cli.db.queries.rate_limits import (
    get_all_global_rate_limits as get_all_global_rate_limits,
)
from songmaker_cli.db.queries.rate_limits import (
    get_rate_limit_setting as get_rate_limit_setting,
)
from songmaker_cli.db.queries.rate_limits import get_user_rate_limits as get_user_rate_limits
from songmaker_cli.db.queries.rate_limits import resolve_rate_limit as resolve_rate_limit
from songmaker_cli.db.queries.rate_limits import (
    upsert_rate_limit_setting as upsert_rate_limit_setting,
)
from songmaker_cli.db.queries.settings import create_preset as create_preset
from songmaker_cli.db.queries.settings import delete_preset as delete_preset
from songmaker_cli.db.queries.settings import (
    get_claude_chat_model as get_claude_chat_model,
)
from songmaker_cli.db.queries.settings import (
    get_claude_scoring_model as get_claude_scoring_model,
)
from songmaker_cli.db.queries.settings import get_default_preset as get_default_preset
from songmaker_cli.db.queries.settings import get_global_defaults as get_global_defaults
from songmaker_cli.db.queries.settings import get_preset as get_preset
from songmaker_cli.db.queries.settings import list_active_models as list_active_models
from songmaker_cli.db.queries.settings import list_all_models as list_all_models
from songmaker_cli.db.queries.settings import list_presets as list_presets
from songmaker_cli.db.queries.settings import list_shared_presets as list_shared_presets
from songmaker_cli.db.queries.settings import name_exists as name_exists
from songmaker_cli.db.queries.settings import save_global_defaults as save_global_defaults
from songmaker_cli.db.queries.settings import set_claude_model as set_claude_model
from songmaker_cli.db.queries.settings import set_default_preset as set_default_preset
from songmaker_cli.db.queries.settings import toggle_model as toggle_model
from songmaker_cli.db.queries.settings import update_preset as update_preset
from songmaker_cli.db.queries.songs import UNSET as UNSET
from songmaker_cli.db.queries.songs import cleanup_song as cleanup_song
from songmaker_cli.db.queries.songs import count_songs as count_songs
from songmaker_cli.db.queries.songs import create_song as create_song
from songmaker_cli.db.queries.songs import delete_song as delete_song
from songmaker_cli.db.queries.songs import disable_song_sharing as disable_song_sharing
from songmaker_cli.db.queries.songs import enable_song_sharing as enable_song_sharing
from songmaker_cli.db.queries.songs import get_song as get_song
from songmaker_cli.db.queries.songs import get_song_by_slug as get_song_by_slug
from songmaker_cli.db.queries.songs import list_expired_songs as list_expired_songs
from songmaker_cli.db.queries.songs import list_songs as list_songs
from songmaker_cli.db.queries.songs import move_song as move_song
from songmaker_cli.db.queries.songs import restore_song as restore_song
from songmaker_cli.db.queries.songs import soft_delete_song as soft_delete_song
from songmaker_cli.db.queries.songs import update_song as update_song
from songmaker_cli.db.queries.versions import delete_version as delete_version
from songmaker_cli.db.queries.versions import get_version as get_version
from songmaker_cli.db.queries.workers import get_worker_identity as get_worker_identity
from songmaker_cli.db.queries.workers import (
    list_worker_identities as list_worker_identities,
)
from songmaker_cli.db.queries.workers import register_worker as register_worker
