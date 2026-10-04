"""Shared filename metadata for graph UI and portable material assets."""
def file_parameter(spec):
    return spec.get('type') in ('String','StringVector') and (
        'FLAGS_FILENAME' in spec.get('flags','') or spec.get('name')=='file' or
        str(spec.get('comment','')).lower().startswith('filename that points to'))
