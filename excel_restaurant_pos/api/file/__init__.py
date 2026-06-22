from .upload_files import upload_public_file
from .download_files import download_public_file

__all__ = ["upload_public_file", "download_public_file"]

file_api_routes = {
    "api.files.upload_public_file": "excel_restaurant_pos.api.file.upload_public_file",
    "api.files.download_public_file": "excel_restaurant_pos.api.file.download_public_file",
}
