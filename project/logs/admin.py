from django.contrib import admin
from import_export.admin import ExportMixin, ImportExportModelAdmin
from import_export import resources
from .models import MachineLog

# Define resource for import/export
class MachineLogResource(resources.ModelResource):
    class Meta:
        model = MachineLog
        fields = ('MACHINE_ID', 'LINE_NUMBER', 'OPERATOR_ID', 'DATE', 'START_TIME', 'END_TIME',
                  'MODE', 'OPERATION_COUNT', 'SKIP_COUNT', 'NEEDLE_STOPTIME', 'Tx_LOG_ID',
                  'STORED_LOG_ID', 'DEVICE_ID', 'RESERVE', 'created_at')

# Admin Configuration
class MachineLogAdmin(ImportExportModelAdmin, admin.ModelAdmin):
    resource_class = MachineLogResource
    list_display = ('MACHINE_ID', 'OPERATOR_ID', 'DATE', 'START_TIME', 'END_TIME', 'MODE','OPERATION_COUNT','SKIP_COUNT','Tx_LOG_ID','STORED_LOG_ID','created_at')
    search_fields = ('MACHINE_ID', 'OPERATOR_ID', 'DATE')
    list_filter = ('DATE', 'MODE')

# Register the model with custom admin
admin.site.register(MachineLog, MachineLogAdmin)
