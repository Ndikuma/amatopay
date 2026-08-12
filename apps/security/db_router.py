class SecurityDatabaseRouter:
    """
    Store security app data in its own database.

    This keeps high-volume request logs and alerts separate from business data,
    making the security app easier to copy, archive, prune, or disable.
    """

    app_label = 'security'
    database = 'security'

    def db_for_read(self, model, **hints):
        if model._meta.app_label == self.app_label:
            return self.database
        return None

    def db_for_write(self, model, **hints):
        if model._meta.app_label == self.app_label:
            return self.database
        return None

    def allow_relation(self, obj1, obj2, **hints):
        if obj1._meta.app_label == self.app_label and obj2._meta.app_label == self.app_label:
            return True
        if self.app_label in {obj1._meta.app_label, obj2._meta.app_label}:
            return False
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label == self.app_label:
            return db == self.database
        if db == self.database:
            return False
        return None
