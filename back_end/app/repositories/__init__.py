"""Repository exports.

Keep the legacy product-resolution repository lazy so the new canonical
pipeline can import the article repository without loading the old ``pn``
stack.  Existing ``from back_end.app.repositories import ...`` imports remain
compatible through module ``__getattr__``.
"""

__all__ = ["ArticleRepository", "ProductRepository", "ReviewQueueRepository"]


def __getattr__(name: str):
    if name == "ArticleRepository":
        from back_end.app.repositories.articles import ArticleRepository

        return ArticleRepository
    if name == "ProductRepository":
        from back_end.app.repositories.products import ProductRepository

        return ProductRepository
    if name == "ReviewQueueRepository":
        from back_end.app.repositories.review_queue import ReviewQueueRepository

        return ReviewQueueRepository
    raise AttributeError(name)
