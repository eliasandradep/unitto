RESERVED_SLUGS = {
    'admin', 'saas-admin', 'billing', 'signup', 'static', 'ping',
    'login', 'logout', 't', 'www', 'api', 'mail', 'app',
}


def is_reserved_slug(slug: str) -> bool:
    return slug.lower() in RESERVED_SLUGS
