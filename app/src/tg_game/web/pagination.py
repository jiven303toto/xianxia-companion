from typing import Optional


def build_pagination_numbers(
    current_page: int,
    total_pages: int,
) -> list[Optional[int]]:
    total_pages = max(int(total_pages or 1), 1)
    current_page = min(max(int(current_page or 1), 1), total_pages)
    if total_pages <= 6:
        return list(range(1, total_pages + 1))
    if current_page <= 3:
        return [1, 2, 3, 4, None, total_pages]
    if current_page >= total_pages - 2:
        return [1, None, total_pages - 3, total_pages - 2, total_pages - 1, total_pages]
    return [
        1,
        None,
        current_page - 1,
        current_page,
        current_page + 1,
        None,
        total_pages,
    ]
