def preprocessing_hook(endpoints, **kwargs):
    """Filter out internal endpoints from the schema"""
    filtered_endpoints = [
        (path, path_regex, method, callback) 
        for path, path_regex, method, callback in endpoints
        if not path.startswith('/api/internal/')
    ]
    return filtered_endpoints


def postprocessing_hook(schema, **kwargs):
    """Add custom information to the schema"""
    schema['info']['x-contact-email'] = 'support@amatopay.com'
    schema['info']['x-contact-url'] = 'https://amatopay.com/contact'
    
    schema['x-rate-limit'] = {
        'limit': 1000,
        'window': 3600,
        'description': 'Rate limit of 1000 requests per hour per API key'
    }
    
    return schema