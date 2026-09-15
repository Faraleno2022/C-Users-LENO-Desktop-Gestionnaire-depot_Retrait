"""Identification de la version déployée, sans accès aux données métier."""
import os


class BuildRevisionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        revision = os.environ.get('RENDER_GIT_COMMIT', '')
        if len(revision) == 40 and all(c in '0123456789abcdef' for c in revision.lower()):
            response['X-EMAB-Revision'] = revision
        return response
