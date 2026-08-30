import io
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive"]
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CREDENTIALS = BASE_DIR / "credentials.json"
DEFAULT_TOKEN = BASE_DIR / "token.json"


class GoogleDriveBackup:
    """Google Drive backup using OAuth 2.0 Desktop/Installed App."""

    def __init__(self, credentials_file=None, folder_id="", folder_name="Vaka_Data", token_file=None):
        # IMPORTANT: OAuth credentials are deliberately fixed to the Vaka folder.
        # This prevents an old/wrong credentials.json from an environment variable
        # or another working directory from being loaded.
        self.credentials_file = DEFAULT_CREDENTIALS
        self.token_file = DEFAULT_TOKEN
        self.folder_id = str(folder_id or "").strip()
        self.folder_name = str(folder_name or "Vaka_Data").strip() or "Vaka_Data"
        self.service = None

    @staticmethod
    def _resolve_path(value, default):
        if not value:
            return default
        p = Path(str(value))
        return p if p.is_absolute() else BASE_DIR / p


    def credentials_path(self):
        """Return the exact OAuth JSON path used by Vaka."""
        return self.credentials_file

    def _ensure(self):
        if self.service is not None:
            return self.service
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build

            cp = self.credentials_file
            tp = self.token_file

            if not cp.exists():
                logger.error("Google Drive OAuth недоступен: не найден %s", cp)
                return None

            try:
                raw = json.loads(cp.read_text(encoding="utf-8"))
            except Exception as e:
                logger.error("Google Drive OAuth: credentials.json повреждён: %s", e)
                return None

            if "installed" not in raw:
                logger.error(
                    "Google Drive OAuth: неверный credentials.json: %s "
                    "(installed=%s, web=%s)",
                    cp,
                    "installed" in raw,
                    "web" in raw,
                )
                return None

            logger.info(
                "Google Drive OAuth: используем credentials.json: %s (тип=installed)",
                cp,
            )

            creds = None
            if tp.exists():
                try:
                    creds = Credentials.from_authorized_user_file(str(tp), SCOPES)
                except Exception:
                    logger.warning("Google Drive OAuth: token.json не удалось прочитать; повторная авторизация.")

            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:
                    logger.warning("Google Drive OAuth: refresh token не сработал: %s", e)
                    creds = None

            if not creds or not creds.valid:
                logger.info("🔐 Google Drive: требуется OAuth авторизация. Откроется браузер.")
                flow = InstalledAppFlow.from_client_secrets_file(str(cp), SCOPES)
                creds = flow.run_local_server(
                    host="localhost",
                    port=0,
                    access_type="offline",
                    prompt="consent",
                )

            tp.write_text(creds.to_json(), encoding="utf-8")
            self.service = build("drive", "v3", credentials=creds, cache_discovery=False)
            logger.info(
                "✅ Google Drive OAuth подключён (аккаунт пользователя); token=%s",
                tp,
            )
            return self.service
        except Exception as e:
            logger.exception("Google Drive OAuth недоступен: %s", e)
            return None

    @staticmethod
    def _escape(value):
        return str(value).replace("\\", "\\\\").replace("'", "\\'")

    def _folder(self):
        svc = self._ensure()
        if not svc:
            return None

        if self.folder_id:
            try:
                item = svc.files().get(
                    fileId=self.folder_id,
                    fields="id,name,mimeType,trashed",
                    supportsAllDrives=True,
                ).execute()
                if item.get("mimeType") == "application/vnd.google-apps.folder" and not item.get("trashed", False):
                    return self.folder_id
            except Exception as e:
                logger.warning("Google Drive: папка по ID недоступна: %s", e)
            self.folder_id = ""

        name = self._escape(self.folder_name)
        q = f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        try:
            rows = svc.files().list(
                q=q,
                spaces="drive",
                fields="files(id,name,mimeType,trashed)",
                pageSize=50,
                orderBy="name",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute().get("files", [])

            if rows:
                self.folder_id = rows[0]["id"]
                logger.info("✅ Google Drive: найдена папка %s", self.folder_name)
                return self.folder_id

            created = svc.files().create(
                body={"name": self.folder_name, "mimeType": "application/vnd.google-apps.folder"},
                fields="id,name",
                supportsAllDrives=True,
            ).execute()
            self.folder_id = created["id"]
            logger.info("✅ Google Drive: создана папка %s", self.folder_name)
            return self.folder_id
        except Exception:
            logger.exception("Google Drive: ошибка поиска/создания папки")
            return None

    def upload(self, path, keep=4):
        svc = self._ensure()
        folder = self._folder()
        if not svc or not folder:
            return False
        try:
            from googleapiclient.http import MediaFileUpload
            path = Path(path)
            if not path.exists():
                logger.error("Google Drive: backup не найден: %s", path)
                return False

            result = svc.files().create(
                body={"name": path.name, "parents": [folder]},
                media_body=MediaFileUpload(str(path), mimetype="application/x-sqlite3", resumable=True),
                fields="id,name",
                supportsAllDrives=True,
            ).execute()
            logger.info("✅ Google Drive backup uploaded: %s", result.get("name", path.name))

            try:
                keep = max(1, int(keep))
            except (TypeError, ValueError):
                keep = 4

            q = f"'{self._escape(folder)}' in parents and trashed = false"
            rows = svc.files().list(
                q=q,
                orderBy="createdTime desc",
                fields="files(id,name,size,createdTime)",
                pageSize=100,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute().get("files", [])

            for old in rows[keep:]:
                try:
                    svc.files().delete(fileId=old["id"], supportsAllDrives=True).execute()
                except Exception:
                    logger.exception("Google Drive: не удалось удалить старую копию %s", old.get("name"))
            return True
        except Exception:
            logger.exception("Google Drive upload failed")
            return False

    def list_backups(self, limit=20):
        svc = self._ensure()
        folder = self._folder()
        if not svc or not folder:
            return []
        try:
            limit = max(1, min(int(limit), 100))
        except (TypeError, ValueError):
            limit = 20
        try:
            q = f"'{self._escape(folder)}' in parents and trashed = false"
            return svc.files().list(
                q=q,
                orderBy="createdTime desc",
                fields="files(id,name,size,createdTime)",
                pageSize=limit,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute().get("files", [])
        except Exception:
            logger.exception("Google Drive: не удалось получить список backup")
            return []

    def download(self, file_id, destination):
        svc = self._ensure()
        if not svc:
            return False
        fh = None
        try:
            from googleapiclient.http import MediaIoBaseDownload
            destination = Path(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            request = svc.files().get_media(fileId=str(file_id), supportsAllDrives=True)
            fh = io.FileIO(str(destination), "wb")
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            logger.info("✅ Google Drive backup downloaded: %s", destination)
            return True
        except Exception:
            logger.exception("Google Drive download failed")
            return False
        finally:
            if fh is not None:
                try:
                    fh.close()
                except Exception:
                    pass
