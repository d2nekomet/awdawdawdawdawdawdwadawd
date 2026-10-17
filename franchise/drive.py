import httpx


class DriveError(RuntimeError):
    pass


class DriveClient:
    """Загрузка файлов в drive.unlim-projects.lol.

    Контракт задаётся переменными окружения: POST multipart-поле `file` на DRIVE_UPLOAD_URL
    с заголовком Authorization: Bearer <DRIVE_API_TOKEN>. Ответ должен быть JSON с полем `url`
    (или `link`). Если ваш API отличается — поправьте `upload` здесь, остальной код не меняется.
    """

    def __init__(self, upload_url: str, api_token: str, http: httpx.AsyncClient):
        self.upload_url = upload_url
        self.api_token = api_token
        self._http = http

    @property
    def configured(self) -> bool:
        return bool(self.upload_url and self.api_token)

    async def upload(self, filename: str, data: bytes, mime: str = "application/octet-stream") -> str:
        if not self.configured:
            raise DriveError("Drive не настроен: задайте DRIVE_UPLOAD_URL и DRIVE_API_TOKEN")
        resp = await self._http.post(
            self.upload_url,
            headers={"Authorization": f"Bearer {self.api_token}"},
            files={"file": (filename, data, mime)},
        )
        if resp.status_code >= 400:
            raise DriveError(f"Drive вернул HTTP {resp.status_code}")
        payload = resp.json()
        url = payload.get("url") or payload.get("link")
        if not url:
            raise DriveError("В ответе Drive нет ссылки на файл")
        return url
