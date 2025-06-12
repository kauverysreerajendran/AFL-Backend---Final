# Standard library imports
from datetime import datetime, timedelta, date

# Django imports
from django.core.exceptions import ValidationError
from django.contrib.auth import authenticate
from django.db.models import (
    F, Sum, Count, Case, When, Value, FloatField, ExpressionWrapper,
    Avg, IntegerField, Q, DurationField
)
from django.db.models.functions import (
    ExtractHour, ExtractMinute, ExtractSecond, Cast
)
from django.http import JsonResponse

# Django REST framework imports
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.authtoken.models import Token
from rest_framework.views import APIView
from rest_framework import status

# Local application imports
from .models import MachineLog, DuplicateLog, ModeMessage, Operator
from .serializers import MachineLogSerializer

@api_view(['POST'])
def log_machine_data(request):
    data = request.data
    print("Processing machine log data...")

    # Validate mode
    try:
        mode = int(data.get("MODE"))
    except (TypeError, ValueError):
        return Response({"message": "Invalid mode format"}, status=400)

    # Validate serializer
    serializer = MachineLogSerializer(data=data)
    if not serializer.is_valid():
        return Response({"message": "Validation failed", "errors": serializer.errors}, status=201)

    validated_data = serializer.validated_data

    machine_id = validated_data.get("MACHINE_ID")
    operator_id = validated_data.get("OPERATOR_ID")
    start_time = validated_data.get("START_TIME")
    end_time = validated_data.get("END_TIME")
    log_date = validated_data.get("DATE")
    str_log_id = validated_data.get("STORED_LOG_ID")

    if not machine_id or not log_date:
        return Response({"message": "MACHINE_ID and DATE are required"}, status=400)

    # Adjust STORED_LOG_ID if needed
    if str_log_id is not None:
        try:
            str_log_id = int(str_log_id)
            if str_log_id > 1000:
                validated_data["STORED_LOG_ID"] = str_log_id - 1000
        except ValueError:
            return Response({"message": "Invalid STORED_LOG_ID format"}, status=400)

    # ✅ Always check for duplicates BEFORE inserting (based on unique constraint)
    if MachineLog.objects.filter(
        MACHINE_ID=machine_id,
        OPERATOR_ID=operator_id,
        START_TIME=start_time,
        END_TIME=end_time,
        DATE=log_date, 

    ).exists():
        return Response({
            "code": 201,
            "message": "Duplicate log entry exists for this machine, operator, and time. Data not saved."
        }, status=201)

    # Save log only if not duplicate
    MachineLog.objects.create(**validated_data)

    return Response({
        "code": 200,
        "message": "Log saved successfully",
    }, status=200)

from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import MachineLog
from .serializers import MachineLogSerializer

@api_view(['GET'])
def get_machine_logs(request):
    """
    View to retrieve machine logs with optional date filtering.
    """
    from_date = request.query_params.get('from_date')
    to_date = request.query_params.get('to_date')
    
    logs = MachineLog.objects.all().order_by('-created_at')
    
    if from_date:
        logs = logs.filter(DATE__gte=from_date)
    if to_date:
        logs = logs.filter(DATE__lte=to_date)
    
    serialized_logs = MachineLogSerializer(logs, many=True).data

    # Add indexing (starting from 1)
    for idx, log in enumerate(serialized_logs, start=1):
        log['index'] = idx

    return Response(serialized_logs)


@api_view(['POST'])
def user_login(request):
    """
    View to handle user login and authenticate using Django's built-in authentication system.
    
    Validates and processes incoming user login data:
    - Authenticates the user
    - Returns a token if authentication is successful
    
    Returns:
        Response with status and message
    """
    data = request.data
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return Response({"message": "Username and password are required"}, status=400)

    user = authenticate(username=username, password=password)
    if user is not None:
        # Authentication successful, generate token
        token, created = Token.objects.get_or_create(user=user)
        return Response({"message": "Login successful", "token": token.key}, status=200)
    else:
        return Response({"message": "Invalid credentials"}, status=400)

@api_view(['GET'])
def get_underperforming_operators(request):
    """
    Fetches the count of underperforming operators.
    
    Criteria:
    - Operators in non-production modes (mode 3, 4, 5)
    - Counts the number of unique `operator_id` values

    Returns:
        JSON response with count
    """
    underperforming_modes = [3, 4, 5]  # Non-production modes
    underperforming_count = (
        MachineLog.objects.filter(mode__in=underperforming_modes)
        .values("operator_id")  # Group by operator
        .distinct()
        .count()
    )

    return Response({"underperforming_operator_count": underperforming_count}, status=200)

@api_view(['GET'])
def get_machine_id_count(request):
    """
    Fetch total number of unique Machine IDs.
    """
    machine_count = MachineLog.objects.values("MACHINE_ID").distinct().count()
    return Response({"machine_id_count": machine_count}, status=200)

@api_view(['GET'])
def get_LINE_NUMBERer_count(request):
    """
    Fetch total number of unique Line Numbers.
    """
    line_count = MachineLog.objects.values("LINE_NUMBER").distinct().count()
    return Response({"LINE_NUMBERer_count": line_count}, status=200)

@api_view(['GET'])
def calculate_line_efficiency(request):
    """
    Calculate efficiency metrics for each production line.
    
    Returns:
        Response with efficiency data for each line including:
        - Total machines
        - Runtime efficiency percentage
    """
    line_stats = (
        MachineLog.objects.values("LINE_NUMBER")
        .annotate(
            total_machines=Count("MACHINE_ID", distinct=True),
            total_runtime=Sum("SKIP_COUNT"),
            total_stoptime=Sum("NEEDLE_STOPTIME")
        )
    )

    response = {}
    for stat in line_stats:
        LINE_NUMBERer = stat["LINE_NUMBER"]
        total_machines = stat["total_machines"]
        total_runtime = stat["total_runtime"]
        total_stoptime = stat["total_stoptime"]

        efficiency = (total_runtime / (total_runtime + total_stoptime)) * 100 if (total_runtime + total_stoptime) > 0 else 0

        response[f"Line {LINE_NUMBERer}"] = {
            "Total_Machines": total_machines,
            "Efficiency": f"{efficiency:.2f}%"
        }

    return Response(response)

def time_to_seconds(time_obj):
    """Helper function to convert HH:MM:SS TimeField to total seconds."""
    return time_obj.hour * 3600 + time_obj.minute * 60 + time_obj.second

@api_view(['GET'])
def calculate_operator_efficiency(request):
    """
    Calculate efficiency metrics for operators based on their working hours.
    
    Returns:
        Response with efficiency percentage for each operator
    """
    logs = MachineLog.objects.values("OPERATOR_ID", "START_TIME", "END_TIME")

    response = []
    standard_work_time = 8 * 3600  # 8 hours in seconds

    for log in logs:
        operator_id = log["OPERATOR_ID"]
        start_time = log["START_TIME"]
        end_time = log["END_TIME"]

        start_seconds = time_to_seconds(start_time)
        end_seconds = time_to_seconds(end_time)

        # Handle cases where END_TIME is on the next day
        if end_seconds < start_seconds:
            end_seconds += 24 * 3600  # Add 24 hours in seconds

        actual_work_time = end_seconds - start_seconds
        efficiency = (actual_work_time / standard_work_time) * 100 if standard_work_time > 0 else 0

        response.append({
            "operator": f"Operator {operator_id}",
            "efficiency": round(efficiency, 2)
        })

    return Response(response)

class MachineLogListView(APIView):
    """
    API View to list all machine logs.
    """
    def get(self, request, format=None):
        machine_logs = MachineLog.objects.all()
        serializer = MachineLogSerializer(machine_logs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

@api_view(['GET'])
def operator_reports_by_name(request, operator_name):
    """
    Generate detailed performance report for a specific operator.
    
    Parameters:
        operator_name: Name of the operator to generate report for
        from_date (optional): Start date filter (YYYY-MM-DD)
        to_date (optional): End date filter (YYYY-MM-DD)
        
    Returns:
        Comprehensive operator performance metrics including:
        - Production vs non-production time
        - Sewing speed
        - Stitch count
        - Needle runtime
        - Daily breakdown in table format
    """
    try:
        if operator_name=="All":
            operator = Operator.objects.all( )
            logs = MachineLog.objects.all()
        else:
            # Fetch operator by name
            operator = Operator.objects.get(operator_name=operator_name)
            logs = MachineLog.objects.filter(OPERATOR_ID=operator.rfid_card_no)    
       
    except Operator.DoesNotExist:
        return Response({"error": "Operator not found"}, status=404)

    # Get date filters from query parameters
    from_date_str = request.GET.get('from_date', '')
    to_date_str = request.GET.get('to_date', '')

    # Apply date filtering if dates are provided
    if from_date_str:
        from_date = datetime.strptime(from_date_str, '%Y-%m-%d').date()
        logs = logs.filter(DATE__gte=from_date)

    if to_date_str:
        to_date = datetime.strptime(to_date_str, '%Y-%m-%d').date()
        logs = logs.filter(DATE__lte=to_date)

    # Exclude records where OPERATOR_ID is 0 AND MODE is 2
    logs = logs.exclude(Q(OPERATOR_ID=0) & Q(MODE=2))

    # Calculate duration in hours for each log entry with time constraints (8:30 AM to 7:30 PM)
    logs = logs.annotate(
        start_seconds=ExpressionWrapper(
            ExtractHour('START_TIME') * 3600 + 
            ExtractMinute('START_TIME') * 60 + 
            ExtractSecond('START_TIME'),
            output_field=FloatField()
        ),
        end_seconds=ExpressionWrapper(
            ExtractHour('END_TIME') * 3600 + 
            ExtractMinute('END_TIME') * 60 + 
            ExtractSecond('END_TIME'),
            output_field=FloatField()
        ),
        # Calculate adjusted start and end times within working hours (8:30 AM to 7:30 PM)
        adjusted_start_seconds=Case(
            When(start_seconds__lt=8.5*3600, then=Value(8.5*3600)),  # 8:30 AM
            When(start_seconds__gt=19.5*3600, then=Value(19.5*3600)),  # 7:30 PM
            default=F('start_seconds'),
            output_field=FloatField()
        ),
        adjusted_end_seconds=Case(
            When(end_seconds__lt=8.5*3600, then=Value(8.5*3600)),  # 8:30 AM
            When(end_seconds__gt=19.5*3600, then=Value(19.5*3600)),  # 7:30 PM
            default=F('end_seconds'),
            output_field=FloatField()
        ),
        # Calculate duration only for the time within working hours
        duration_hours=Case(
            # Case when both start and end are outside working hours
            When(
                Q(end_seconds__lte=8.5*3600) | Q(start_seconds__gte=19.5*3600),
                then=Value(0)
            ),
            # Case when log spans working hours
            default=ExpressionWrapper(
                (F('adjusted_end_seconds') - F('adjusted_start_seconds')) / 3600,
                output_field=FloatField()
            ),
            output_field=FloatField()
        ),
        reserve_numeric=Cast('RESERVE', output_field=IntegerField())
    ).filter(duration_hours__gt=0)  # Only include logs with positive duration within working hours

    # Filter out break times
    logs = logs.exclude(
        Q(start_seconds__gte=10.5*3600, end_seconds__lte=10.6667*3600) |  # 10:30-10:40
        Q(start_seconds__gte=13.3333*3600, end_seconds__lte=14*3600) |    # 13:20-14:00
        Q(start_seconds__gte=16.3333*3600, end_seconds__lte=16.5*3600)    # 16:20-16:30
    )

    # Calculate total working days and available hours (10 hours per day accounting for breaks)
    total_working_days = logs.values('DATE').distinct().count()
    total_available_hours = total_working_days * 10  # 10 hours per working day

    # Calculate total hours for each mode
    mode_hours = logs.values('MODE').annotate(
        total_hours=Sum('duration_hours')
    )

    # Initialize hour counters
    total_production_hours = 0
    total_meeting_hours = 0
    total_no_feeding_hours = 0
    total_maintenance_hours = 0

    # Sum hours for each mode
    for mode in mode_hours:
        if mode['MODE'] == 1:  # Sewing (Production)
            total_production_hours = mode['total_hours'] or 0
        elif mode['MODE'] == 4:  # Meeting
            total_meeting_hours = mode['total_hours'] or 0
        elif mode['MODE'] == 3:  # No Feeding
            total_no_feeding_hours = mode['total_hours'] or 0
        elif mode['MODE'] == 5:  # Maintenance
            total_maintenance_hours = mode['total_hours'] or 0

    # Calculate total idle hours
    total_idle_hours = max(total_available_hours - (
        total_production_hours + 
        total_no_feeding_hours + 
        total_meeting_hours + 
        total_maintenance_hours
    ), 0)

    # Calculate non-productive time components
    total_non_production_hours = (
        total_no_feeding_hours + 
        total_meeting_hours + 
        total_maintenance_hours + 
        total_idle_hours
    )

    # Calculate percentages
    production_percentage = (total_production_hours / total_available_hours * 100) if total_available_hours > 0 else 0
    npt_percentage = (total_non_production_hours / total_available_hours * 100) if total_available_hours > 0 else 0

    # Calculate Average Sewing Speed
    valid_speed_logs = logs.filter(reserve_numeric__gt=0)
    average_sewing_speed = valid_speed_logs.aggregate(
        avg_speed=Avg('reserve_numeric')
    )['avg_speed'] or 0

    # Calculate total stitch count
    total_OPERATION_COUNT = logs.aggregate(
        total=Sum('OPERATION_COUNT', default=0)
    )['total'] or 0

    # Calculate Needle Runtime metrics
    sewing_logs = logs.filter(MODE=1)  # Only sewing mode logs
    total_SKIP_COUNT = sewing_logs.aggregate(
        total_runtime=Sum('SKIP_COUNT', default=0)
    )['total_runtime'] or 0
    
    SKIP_COUNT_instances = sewing_logs.count()
    average_SKIP_COUNT = total_SKIP_COUNT / SKIP_COUNT_instances if SKIP_COUNT_instances > 0 else 0
    
    # Convert needle runtime from seconds to hours for percentage calculation
    total_SKIP_COUNT_hours = total_SKIP_COUNT / 3600
    SKIP_COUNT_percentage = (total_SKIP_COUNT_hours / total_production_hours * 100) if total_production_hours > 0 else 0

    # Fetch Table Data (daily breakdown)
    table_data = logs.values('DATE', 'OPERATOR_ID').annotate(
    sewing_hours=Sum(Case(
        When(MODE=1, then=F('duration_hours')),
        default=Value(0),
        output_field=FloatField()
    )),
    meeting_hours=Sum(Case(
        When(MODE=4, then=F('duration_hours')),
        default=Value(0),
        output_field=FloatField()
    )),
    no_feeding_hours=Sum(Case(
        When(MODE=3, then=F('duration_hours')),
        default=Value(0),
        output_field=FloatField()
    )),
    maintenance_hours=Sum(Case(
        When(MODE=5, then=F('duration_hours')),
        default=Value(0),
        output_field=FloatField()
    )),
    total_OPERATION_COUNT=Sum('OPERATION_COUNT'),
    sewing_speed=Avg(Case(
        When(reserve_numeric__gt=0, then=F('reserve_numeric')),
        default=Value(0),
        output_field=FloatField()
    )),
    SKIP_COUNT=Sum('SKIP_COUNT')
    ).annotate(
    total_hours=Value(10, output_field=FloatField()),
    idle_hours=Value(10, output_field=FloatField()) - 
             (F('sewing_hours') + F('meeting_hours') + 
              F('no_feeding_hours') + F('maintenance_hours')),
    productive_time_percentage=(F('sewing_hours') / 10) * 100,
    npt_percentage=100 - (F('sewing_hours') / 10) * 100
    ).order_by('DATE', 'OPERATOR_ID')

# Now format the data, fetching operator name from the Operator model
    formatted_table_data = []
    for data in table_data:
    # Get operator details from the Operator model
        try:
            operator = Operator.objects.get( rfid_card_no=data['OPERATOR_ID'])
            operator_name = operator.operator_name # Assuming the name field is called 'name'
            rfid_card_no = operator.rfid_card_no  # Get RFID card number if needed
        except Operator.DoesNotExist:
            operator_name = "Unknown"
            rfid_card_no = "Unknown"
    
        formatted_table_data.append({
            'Date': str(data['DATE']),
            'Operator ID': data['OPERATOR_ID'],
            'Operator Name': operator_name,
            'Total Hours': round(data['total_hours'], 2),
            'Sewing Hours': round(data['sewing_hours'], 2),
            'Idle Hours': round(max(data['idle_hours'], 0), 2),
            'Meeting Hours': round(data['meeting_hours'], 2),
            'No Feeding Hours': round(data['no_feeding_hours'], 2),
            'Maintenance Hours': round(data['maintenance_hours'], 2),
            'Productive Time in %': round(data['productive_time_percentage'], 2),
            'NPT in %': round(data['npt_percentage'], 2),
            'Sewing Speed': round(data['sewing_speed'], 2),
            'Stitch Count': data['total_OPERATION_COUNT'],
            'Needle Runtime': data['SKIP_COUNT']
        })

    return Response({
        "totalProductionHours": round(total_production_hours, 2),
        "totalNonProductionHours": round(total_non_production_hours, 2),
        "totalIdleHours": round(total_idle_hours, 2),
        "productionPercentage": round(production_percentage, 2),
        "nptPercentage": round(npt_percentage, 2),
        "averageSewingSpeed": round(average_sewing_speed, 2),
        "totalStitchCount": total_OPERATION_COUNT,
        "totalNeedleRuntime": round(average_SKIP_COUNT, 2),
        "needleRuntimePercentage": round(SKIP_COUNT_percentage, 2),
        "tableData": formatted_table_data,
        "totalHours": round(total_available_hours, 2),
        "totalPT": round(total_production_hours, 2),
        "totalNPT": round(total_non_production_hours, 2)
    })

from django.db.models import Sum, Case, When, Value, FloatField, F, ExpressionWrapper, Q, IntegerField, Avg, Count
from django.db.models.functions import ExtractHour, ExtractMinute, ExtractSecond, Cast
from rest_framework.decorators import api_view
from rest_framework.response import Response
from datetime import datetime
from .models import MachineLog

def process_line_data(logs, LINE_NUMBERer):
    """Helper function to process data for a single line"""
    # Calculate total ideal hours (sum of all Mode 2 durations)
    ideal_hours_data = logs.filter(MODE=2).aggregate(
        total_ideal=Sum('duration_hours')
    )
    total_ideal_hours = ideal_hours_data['total_ideal'] or 0

    # Get machine counts per day
    daily_machine_counts = logs.values('DATE').annotate(
        machine_count=Count('MACHINE_ID', distinct=True)
    ).order_by('DATE')

    # Calculate total working days and average machines per day
    total_working_days = len(daily_machine_counts)
    average_machines = sum(item['machine_count'] for item in daily_machine_counts) / total_working_days if total_working_days > 0 else 0

    # Create a dictionary of date to machine count
    date_machine_counts = {item['DATE']: item['machine_count'] for item in daily_machine_counts}

    # Get aggregated data by date
    daily_data = logs.values('DATE').annotate(
        sewing_hours=Sum(Case(
            When(MODE=1, then=F('duration_hours')),
            default=Value(0),
            output_field=FloatField()
        )),
        no_feeding_hours=Sum(Case(
            When(MODE=3, then=F('duration_hours')),
            default=Value(0),
            output_field=FloatField()
        )),
        meeting_hours=Sum(Case(
            When(MODE=4, then=F('duration_hours')),
            default=Value(0),
            output_field=FloatField()
        )),
        maintenance_hours=Sum(Case(
            When(MODE=5, then=F('duration_hours')),
            default=Value(0),
            output_field=FloatField()
        )),
        idle_hours=Sum(Case(
            When(MODE=2, then=F('duration_hours')),
            default=Value(0),
            output_field=FloatField()
        )),
        total_OPERATION_COUNT=Sum('OPERATION_COUNT'),
        sewing_speed=Avg(Case(
            When(reserve_numeric__gt=0, then=F('reserve_numeric')),
            default=Value(0),
            output_field=FloatField()
        )),
        SKIP_COUNT=Sum('SKIP_COUNT')
    ).order_by('DATE')

    # Calculate totals
    total_sewing_hours = 0
    total_no_feeding_hours = 0
    total_meeting_hours = 0
    total_maintenance_hours = 0
    total_idle_hours = 0
    total_OPERATION_COUNT = 0
    total_SKIP_COUNT = 0
    total_hours = 0  # Sum of all actual hours (PT + NPT)

    formatted_table_data = []
    for data in daily_data:
        date = data['DATE']
        machine_count = date_machine_counts.get(date, 1)
        
        sewing_hours = data['sewing_hours'] or 0
        no_feeding_hours = data['no_feeding_hours'] or 0
        meeting_hours = data['meeting_hours'] or 0
        maintenance_hours = data['maintenance_hours'] or 0
        idle_hours = data['idle_hours'] or 0
        
        # Calculate PT and NPT
        productive_time = sewing_hours
        non_productive_time = no_feeding_hours + meeting_hours + maintenance_hours + idle_hours
        daily_total_hours = productive_time + non_productive_time
        
        # Accumulate to total hours
        total_hours += daily_total_hours
        
        # Calculate percentages
        productive_time_percentage = (productive_time / daily_total_hours * 100) if daily_total_hours > 0 else 0
        non_productive_time_percentage = (non_productive_time / daily_total_hours * 100) if daily_total_hours > 0 else 0
        
        formatted_table_data.append({
            'Date': str(date),
            'Sewing Hours (PT)': round(sewing_hours, 2),
            'No Feeding Hours': round(no_feeding_hours, 2),
            'Meeting Hours': round(meeting_hours, 2),
            'Maintenance Hours': round(maintenance_hours, 2),
            'Idle Hours': round(idle_hours, 2),
            'Total Hours': round(daily_total_hours, 2),
            'Productive Time (PT) %': round(productive_time_percentage, 2),
            'Non-Productive Time (NPT) %': round(non_productive_time_percentage, 2),
            'Sewing Speed': round(data['sewing_speed'], 2),
            'Stitch Count': data['total_OPERATION_COUNT'],
            'Needle Runtime': data['SKIP_COUNT'],
            'Machine Count': machine_count
        })

        # Accumulate totals
        total_sewing_hours += sewing_hours
        total_no_feeding_hours += no_feeding_hours
        total_meeting_hours += meeting_hours
        total_maintenance_hours += maintenance_hours
        total_idle_hours += idle_hours
        total_OPERATION_COUNT += data['total_OPERATION_COUNT'] or 0
        total_SKIP_COUNT += data['SKIP_COUNT'] or 0

    # Calculate overall PT and NPT
    total_productive_time = total_sewing_hours
    total_non_productive_time = (
        total_no_feeding_hours + 
        total_meeting_hours + 
        total_maintenance_hours + 
        total_idle_hours
    )
    
    # Calculate overall percentages
    total_productive_percentage = (total_productive_time / total_hours * 100) if total_hours > 0 else 0
    total_non_productive_percentage = (total_non_productive_time / total_hours * 100) if total_hours > 0 else 0
    utilization_percentage = (total_hours / total_ideal_hours * 100) if total_ideal_hours > 0 else 0

    # Calculate average sewing speed
    valid_speed_logs = logs.filter(reserve_numeric__gt=0)
    average_sewing_speed = valid_speed_logs.aggregate(
        avg_speed=Avg('reserve_numeric')
    )['avg_speed'] or 0

    # Calculate needle runtime percentage
    sewing_logs = logs.filter(MODE=1)
    SKIP_COUNT_instances = sewing_logs.count()
    average_SKIP_COUNT = total_SKIP_COUNT / SKIP_COUNT_instances if SKIP_COUNT_instances > 0 else 0
    total_SKIP_COUNT_hours = total_SKIP_COUNT / 3600
    SKIP_COUNT_percentage = (total_SKIP_COUNT_hours / total_productive_time * 100) if total_productive_time > 0 else 0

    return {
        "lineNumber": LINE_NUMBERer,
        "totalIdealHours": round(total_ideal_hours, 2),
        "utilizationPercentage": round(utilization_percentage, 2),
        "totalWorkingDays": total_working_days,
        "averageMachines": round(average_machines, 2),
        "totalHours": round(total_hours, 2),
        "totalProductiveTime": {
            "hours": round(total_productive_time, 2),
            "percentage": round(total_productive_percentage, 2)
        },
        "totalNonProductiveTime": {
            "hours": round(total_non_productive_time, 2),
            "percentage": round(total_non_productive_percentage, 2),
            "breakdown": {
                "noFeedingHours": round(total_no_feeding_hours, 2),
                "meetingHours": round(total_meeting_hours, 2),
                "maintenanceHours": round(total_maintenance_hours, 2),
                "idleHours": round(total_idle_hours, 2)
            }
        },
        "totalStitchCount": total_OPERATION_COUNT,
        "averageSewingSpeed": round(average_sewing_speed, 2),
        "totalNeedleRuntime": round(average_SKIP_COUNT, 2),
        "needleRuntimePercentage": round(SKIP_COUNT_percentage, 2),
        "tableData": formatted_table_data
    }

@api_view(['GET'])
def line_reports(request, LINE_NUMBERer):
    try:
        # Get valid operator IDs from Operator model
        valid_operators = Operator.objects.values_list('rfid_card_no', flat=True)
        
        # Handle "all" case - convert LINE_NUMBERer to string first
        LINE_NUMBERer_str = str(LINE_NUMBERer)
        if LINE_NUMBERer_str.lower() == 'all':
            logs = MachineLog.objects.filter(OPERATOR_ID__in=valid_operators)
            all_lines = True
        else:
            # Convert back to integer if it's a numeric line number
            LINE_NUMBERer = int(LINE_NUMBERer_str)
            logs = MachineLog.objects.filter(LINE_NUMBER=LINE_NUMBERer, OPERATOR_ID__in=valid_operators)
            all_lines = False
    except MachineLog.DoesNotExist:
        return Response({"error": "Data not found"}, status=404)
    except ValueError:
        return Response({"error": "Invalid line number"}, status=400)

    # Get date filters from query parameters
    from_date_str = request.GET.get('from_date', '')
    to_date_str = request.GET.get('to_date', '')

    # Apply date filtering if dates are provided
    if from_date_str:
        from_date = datetime.strptime(from_date_str, '%Y-%m-%d').date()
        logs = logs.filter(DATE__gte=from_date)

    if to_date_str:
        to_date = datetime.strptime(to_date_str, '%Y-%m-%d').date()
        logs = logs.filter(DATE__lte=to_date)

    # Calculate duration in hours for each log entry
    logs = logs.annotate(
        start_seconds=ExpressionWrapper(
            ExtractHour('START_TIME') * 3600 + 
            ExtractMinute('START_TIME') * 60 + 
            ExtractSecond('START_TIME'),
            output_field=FloatField()
        ),
        end_seconds=ExpressionWrapper(
            ExtractHour('END_TIME') * 3600 + 
            ExtractMinute('END_TIME') * 60 + 
            ExtractSecond('END_TIME'),
            output_field=FloatField()
        ),
        duration_hours=ExpressionWrapper(
            (F('end_seconds') - F('start_seconds')) / 3600,
            output_field=FloatField()
        ),
        reserve_numeric=Cast('RESERVE', output_field=IntegerField())
    )

    # Filter for working hours (8:25 AM to 7:35 PM)
    logs = logs.filter(
        start_seconds__gte=30300,  # 8:25 AM (8.416667 * 3600)
        end_seconds__lte=70500     # 7:35 PM (19.583333 * 3600)
    )

    # Exclude specific break periods (entirely within these ranges)
    logs = logs.exclude(
        Q(start_seconds__gte=37800, end_seconds__lte=38400) |  # 10:30-10:40
        Q(start_seconds__gte=48000, end_seconds__lte=50400) |  # 13:20-14:00
        Q(start_seconds__gte=58800, end_seconds__lte=59400)    # 16:20-16:30
    )

    # For "all" case, we'll group by line number
    if all_lines:
        # Get distinct line numbers
        LINE_NUMBERers = logs.order_by('LINE_NUMBER').values_list('LINE_NUMBER', flat=True).distinct()
        
        all_line_reports = []
        summary_data = {
            "totalIdealHours": 0,
            "totalHours": 0,
            "totalProductiveTime": 0,
            "totalNonProductiveTime": 0,
            "totalStitchCount": 0,
            "totalNeedleRuntime": 0,
            "averageSewingSpeed": 0,
            "totalWorkingDays": 0,
            "averageMachines": 0
        }
        
        speed_sum = 0
        speed_count = 0
        SKIP_COUNT_count = 0
        
        for line_num in LINE_NUMBERers:
            line_logs = logs.filter(LINE_NUMBER=line_num)
            
            # Process data for this line (similar to single line processing)
            line_report = process_line_data(line_logs, str(line_num))
            all_line_reports.append(line_report)
            
            # Accumulate summary data
            summary_data["totalIdealHours"] += line_report["totalIdealHours"]
            summary_data["totalHours"] += line_report["totalHours"]
            summary_data["totalProductiveTime"] += line_report["totalProductiveTime"]["hours"]
            summary_data["totalNonProductiveTime"] += line_report["totalNonProductiveTime"]["hours"]
            summary_data["totalStitchCount"] += line_report["totalStitchCount"]
            summary_data["totalNeedleRuntime"] += line_report["totalNeedleRuntime"]
            summary_data["totalWorkingDays"] = max(summary_data["totalWorkingDays"], line_report["totalWorkingDays"])
            summary_data["averageMachines"] += line_report["averageMachines"]
            
            # For averages
            speed_sum += line_report["averageSewingSpeed"] * line_report["totalHours"]
            speed_count += line_report["totalHours"]
            SKIP_COUNT_count += line_report["totalProductiveTime"]["hours"] if line_report["totalProductiveTime"]["hours"] > 0 else 0
        
        # Calculate weighted averages
        if speed_count > 0:
            summary_data["averageSewingSpeed"] = speed_sum / speed_count
        if len(all_line_reports) > 0:
            summary_data["averageMachines"] = summary_data["averageMachines"] / len(all_line_reports)
        if summary_data["totalProductiveTime"] > 0:
            summary_data["needleRuntimePercentage"] = (summary_data["totalNeedleRuntime"] / summary_data["totalProductiveTime"]) * 100
        
        return Response({
            "allLinesReport": all_line_reports,
            "summary": {
                "totalLines": len(all_line_reports),
                "totalIdealHours": round(summary_data["totalIdealHours"], 2),
                "utilizationPercentage": round((summary_data["totalHours"] / summary_data["totalIdealHours"] * 100) if summary_data["totalIdealHours"] > 0 else 0, 2),
                "totalWorkingDays": summary_data["totalWorkingDays"],
                "averageMachines": round(summary_data["averageMachines"], 2),
                "totalHours": round(summary_data["totalHours"], 2),
                "totalProductiveTime": {
                    "hours": round(summary_data["totalProductiveTime"], 2),
                    "percentage": round((summary_data["totalProductiveTime"] / summary_data["totalHours"] * 100) if summary_data["totalHours"] > 0 else 0, 2)
                },
                "totalNonProductiveTime": {
                    "hours": round(summary_data["totalNonProductiveTime"], 2),
                    "percentage": round((summary_data["totalNonProductiveTime"] / summary_data["totalHours"] * 100) if summary_data["totalHours"] > 0 else 0, 2)
                },
                "totalStitchCount": summary_data["totalStitchCount"],
                "averageSewingSpeed": round(summary_data["averageSewingSpeed"], 2),
                "totalNeedleRuntime": round(summary_data["totalNeedleRuntime"], 2),
                "needleRuntimePercentage": round(summary_data.get("needleRuntimePercentage", 0), 2)
            }
        })
    else:
        # Process single line data
        line_report = process_line_data(logs, str(LINE_NUMBERer))
        return Response(line_report)

from django.db.models import Sum, Case, When, Value, FloatField, F, ExpressionWrapper, Q, IntegerField, Avg, Count
from django.db.models.functions import ExtractHour, ExtractMinute, ExtractSecond, Cast
from rest_framework.decorators import api_view
from rest_framework.response import Response
from datetime import datetime
from .models import MachineLog

def process_machine_data(logs, machine_id):
    """Helper function to process data for a single machine"""
    # Calculate total working days and available hours (11 hours per day)
    distinct_dates = logs.dates('DATE', 'day')
    total_working_days = distinct_dates.count()
    total_available_hours = total_working_days * 11

    # Get aggregated data by date
    daily_data = logs.values('DATE').annotate(
        sewing_hours=Sum(Case(
            When(MODE=1, then=F('duration_hours')),
            default=Value(0),
            output_field=FloatField()
        )),
        no_feeding_hours=Sum(Case(
            When(MODE=3, then=F('duration_hours')),
            default=Value(0),
            output_field=FloatField()
        )),
        meeting_hours=Sum(Case(
            When(MODE=4, then=F('duration_hours')),
            default=Value(0),
            output_field=FloatField()
        )),
        maintenance_hours=Sum(Case(
            When(MODE=5, then=F('duration_hours')),
            default=Value(0),
            output_field=FloatField()
        )),
        idle_hours=Sum(Case(
            When(MODE=2, then=F('duration_hours')),
            default=Value(0),
            output_field=FloatField()
        )),
        total_OPERATION_COUNT=Sum('OPERATION_COUNT'),
        sewing_speed=Avg(Case(
            When(reserve_numeric__gt=0, then=F('reserve_numeric')),
            default=Value(0),
            output_field=FloatField()
        )),
        SKIP_COUNT=Sum('SKIP_COUNT')
    ).order_by('DATE')

    # Calculate totals
    total_sewing_hours = 0
    total_no_feeding_hours = 0
    total_meeting_hours = 0
    total_maintenance_hours = 0
    total_idle_hours = 0
    total_OPERATION_COUNT = 0
    total_SKIP_COUNT = 0
    total_hours = 0

    formatted_table_data = []
    for data in daily_data:
        sewing_hours = data['sewing_hours'] or 0
        no_feeding_hours = data['no_feeding_hours'] or 0
        meeting_hours = data['meeting_hours'] or 0
        maintenance_hours = data['maintenance_hours'] or 0
        idle_hours = data['idle_hours'] or 0
        
        # Calculate PT and NPT
        productive_time = sewing_hours
        non_productive_time = no_feeding_hours + meeting_hours + maintenance_hours + idle_hours
        daily_total_hours = productive_time + non_productive_time
        
        # Accumulate to total hours
        total_hours += daily_total_hours
        
        # Calculate percentages
        productive_time_percentage = (productive_time / daily_total_hours * 100) if daily_total_hours > 0 else 0
        non_productive_time_percentage = (non_productive_time / daily_total_hours * 100) if daily_total_hours > 0 else 0
        
        formatted_table_data.append({
            'Date': str(data['DATE']),
            'Sewing Hours (PT)': round(sewing_hours, 2),
            'No Feeding Hours': round(no_feeding_hours, 2),
            'Meeting Hours': round(meeting_hours, 2),
            'Maintenance Hours': round(maintenance_hours, 2),
            'Idle Hours': round(idle_hours, 2),
            'Total Hours': round(daily_total_hours, 2),
            'Productive Time (PT) %': round(productive_time_percentage, 2),
            'Non-Productive Time (NPT) %': round(non_productive_time_percentage, 2),
            'Sewing Speed': round(data['sewing_speed'], 2),
            'Stitch Count': data['total_OPERATION_COUNT'],
            'Needle Runtime': data['SKIP_COUNT'],
            'Machine ID': machine_id
        })

        # Accumulate totals
        total_sewing_hours += sewing_hours
        total_no_feeding_hours += no_feeding_hours
        total_meeting_hours += meeting_hours
        total_maintenance_hours += maintenance_hours
        total_idle_hours += idle_hours
        total_OPERATION_COUNT += data['total_OPERATION_COUNT'] or 0
        total_SKIP_COUNT += data['SKIP_COUNT'] or 0

    # Calculate overall PT and NPT
    total_productive_time = total_sewing_hours
    total_non_productive_time = (
        total_no_feeding_hours + 
        total_meeting_hours + 
        total_maintenance_hours + 
        total_idle_hours
    )
    
    # Calculate overall percentages
    total_productive_percentage = (total_productive_time / total_hours * 100) if total_hours > 0 else 0
    total_non_productive_percentage = (total_non_productive_time / total_hours * 100) if total_hours > 0 else 0

    # Calculate average sewing speed
    valid_speed_logs = logs.filter(reserve_numeric__gt=0)
    average_sewing_speed = valid_speed_logs.aggregate(
        avg_speed=Avg('reserve_numeric')
    )['avg_speed'] or 0

    return {
        "machineId": machine_id,
        "totalAvailableHours": total_available_hours,
        "totalWorkingDays": total_working_days,
        "totalHours": round(total_hours, 2),
        "totalProductiveTime": {
            "hours": round(total_productive_time, 2),
            "percentage": round(total_productive_percentage, 2)
        },
        "totalNonProductiveTime": {
            "hours": round(total_non_productive_time, 2),
            "percentage": round(total_non_productive_percentage, 2),
            "breakdown": {
                "noFeedingHours": round(total_no_feeding_hours, 2),
                "meetingHours": round(total_meeting_hours, 2),
                "maintenanceHours": round(total_maintenance_hours, 2),
                "idleHours": round(total_idle_hours, 2)
            }
        },
        "totalStitchCount": total_OPERATION_COUNT,
        "averageSewingSpeed": round(average_sewing_speed, 2),
        "totalNeedleRuntime": round(total_SKIP_COUNT, 2),
        "tableData": formatted_table_data
    }

@api_view(['GET'])
def machine_reports(request, machine_id):
    try:
        # Get valid operator IDs from Operator model
        valid_operators = Operator.objects.values_list('rfid_card_no', flat=True)
        
        # Handle "all" case - convert machine_id to string first
        machine_id_str = str(machine_id)
        if machine_id_str.lower() == 'all':
            logs = MachineLog.objects.filter(OPERATOR_ID__in=valid_operators)
            all_machines = True
        else:
            logs = MachineLog.objects.filter(MACHINE_ID=machine_id, OPERATOR_ID__in=valid_operators)
            all_machines = False
    except MachineLog.DoesNotExist:
        return Response({"error": "Data not found"}, status=404)
    except ValueError:
        return Response({"error": "Invalid machine ID"}, status=400)

    # Get date filters from query parameters
    from_date_str = request.GET.get('from_date', '')
    to_date_str = request.GET.get('to_date', '')

    # Apply date filtering if dates are provided
    if from_date_str:
        from_date = datetime.strptime(from_date_str, '%Y-%m-%d').date()
        logs = logs.filter(DATE__gte=from_date)

    if to_date_str:
        to_date = datetime.strptime(to_date_str, '%Y-%m-%d').date()
        logs = logs.filter(DATE__lte=to_date)

    # Calculate duration in hours for each log entry
    logs = logs.annotate(
        start_seconds=ExpressionWrapper(
            ExtractHour('START_TIME') * 3600 + 
            ExtractMinute('START_TIME') * 60 + 
            ExtractSecond('START_TIME'),
            output_field=FloatField()
        ),
        end_seconds=ExpressionWrapper(
            ExtractHour('END_TIME') * 3600 + 
            ExtractMinute('END_TIME') * 60 + 
            ExtractSecond('END_TIME'),
            output_field=FloatField()
        ),
        duration_hours=ExpressionWrapper(
            (F('end_seconds') - F('start_seconds')) / 3600,
            output_field=FloatField()
        ),
        reserve_numeric=Cast('RESERVE', output_field=IntegerField())
    )

    # Filter for working hours (8:25 AM to 7:35 PM)
    logs = logs.filter(
        start_seconds__gte=30300,  # 8:25 AM (8.416667 * 3600)
        end_seconds__lte=70500     # 7:35 PM (19.583333 * 3600)
    )

    # Exclude specific break periods (entirely within these ranges)
    logs = logs.exclude(
        Q(start_seconds__gte=37800, end_seconds__lte=38400) |  # 10:30-10:40
        Q(start_seconds__gte=48000, end_seconds__lte=50400) |  # 13:20-14:00
        Q(start_seconds__gte=58800, end_seconds__lte=59400)    # 16:20-16:30
    )

    # For "all" case, we'll group by machine ID
    if all_machines:
        # Get distinct machine IDs
        machine_ids = logs.order_by('MACHINE_ID').values_list('MACHINE_ID', flat=True).distinct()
        
        all_machine_reports = []
        
        for machine_id in machine_ids:
            machine_logs = logs.filter(MACHINE_ID=machine_id)
            
            # Process data for this machine
            machine_report = process_machine_data(machine_logs, machine_id)
            all_machine_reports.append(machine_report)
        
        return Response({
            "allMachinesReport": all_machine_reports,
            "totalMachines": len(all_machine_reports)
        })
    else:
        # Process single machine data
        machine_report = process_machine_data(logs, machine_id)
        return Response(machine_report)


@api_view(['GET'])
def all_machines_report(request):
    try:
        # Get valid operator IDs from Operator model
        valid_operators = Operator.objects.values_list('rfid_card_no', flat=True)
        logs = MachineLog.objects.filter(OPERATOR_ID__in=valid_operators)
    except Exception as e:
        return Response({
                    "code": 201,
                    "message": "STR Log ID already exists for this machine and date, data not saved"
        }, status=201)

    # Get date filters from query parameters
    from_date_str = request.GET.get('from_date', '')
    to_date_str = request.GET.get('to_date', '')

    # Apply date filtering if dates are provided
    if from_date_str:
        try:
            from_date = datetime.strptime(from_date_str, '%Y-%m-%d').date()
            logs = logs.filter(DATE__gte=from_date)
        except ValueError:
            return Response({"error": "Invalid from_date format. Use YYYY-MM-DD"}, status=400)

    if to_date_str:
        try:
            to_date = datetime.strptime(to_date_str, '%Y-%m-%d').date()
            logs = logs.filter(DATE__lte=to_date)
        except ValueError:
            return Response({"error": "Invalid to_date format. Use YYYY-MM-DD"}, status=400)

    # Calculate duration in hours for each log entry
    logs = logs.annotate(
        start_seconds=ExpressionWrapper(
            ExtractHour('START_TIME') * 3600 + 
            ExtractMinute('START_TIME') * 60 + 
            ExtractSecond('START_TIME'),
            output_field=FloatField()
        ),
        end_seconds=ExpressionWrapper(
            ExtractHour('END_TIME') * 3600 + 
            ExtractMinute('END_TIME') * 60 + 
            ExtractSecond('END_TIME'),
            output_field=FloatField()
        ),
        duration_hours=ExpressionWrapper(
            (F('end_seconds') - F('start_seconds')) / 3600,
            output_field=FloatField()
        ),
        reserve_numeric=Cast('RESERVE', output_field=IntegerField())
    ).filter(
        start_seconds__gte=30300,  # 8:25 AM (8.416667 * 3600)
        end_seconds__lte=70500     # 7:35 PM (19.583333 * 3600)
    ).exclude(
        Q(start_seconds__gte=37800, end_seconds__lte=38400) |  # 10:30-10:40
        Q(start_seconds__gte=48000, end_seconds__lte=50400) |  # 13:20-14:00
        Q(start_seconds__gte=58800, end_seconds__lte=59400)    # 16:20-16:30
    )

    # Get distinct machine IDs
    machine_ids = logs.order_by('MACHINE_ID').values_list('MACHINE_ID', flat=True).distinct()
    
    all_machine_reports = []
    
    for machine_id in machine_ids:
        machine_logs = logs.filter(MACHINE_ID=machine_id)
        
        # Process data for this machine
        try:
            machine_report = process_machine_data(machine_logs, machine_id)
            all_machine_reports.append(machine_report)
        except Exception as e:
            print(f"Error processing machine {machine_id}: {str(e)}")
            continue
    
    return Response({
        "allMachinesReport": all_machine_reports,
        "totalMachines": len(all_machine_reports),
        "from_date": from_date_str,
        "to_date": to_date_str
    })
@api_view(['GET'])
def operator_reports_all(request):
    """
    Generate summary performance reports for all operators.
    
    Parameters:
        from_date (optional): Start date filter (YYYY-MM-DD)
        to_date (optional): End date filter (YYYY-MM-DD)
        
    Returns:
        List of operator performance summaries including:
        - Operator ID and name
        - Production vs non-production hours
        - Efficiency percentages
    """
    operators = Operator.objects.all()
    from_date_str = request.GET.get('from_date', '')
    to_date_str = request.GET.get('to_date', '')

    all_operators_data = []

    for operator in operators:
        logs = MachineLog.objects.filter(OPERATOR_ID=operator.rfid_card_no)

        # Apply date filtering if dates are provided
        if from_date_str:
            from_date = datetime.strptime(from_date_str, '%Y-%m-%d').date()
            logs = logs.filter(DATE__gte=from_date)

        if to_date_str:
            to_date = datetime.strptime(to_date_str, '%Y-%m-%d').date()
            logs = logs.filter(DATE__lte=to_date)

        # Exclude records where OPERATOR_ID is 0 AND MODE is 2
        logs = logs.exclude(Q(OPERATOR_ID=0) & Q(MODE=2))

        # Calculate duration in hours
        logs = logs.annotate(
            start_seconds=ExpressionWrapper(
                ExtractHour('START_TIME') * 3600 +
                ExtractMinute('START_TIME') * 60 +
                ExtractSecond('START_TIME'),
                output_field=FloatField()
            ),
            end_seconds=ExpressionWrapper(
                ExtractHour('END_TIME') * 3600 +
                ExtractMinute('END_TIME') * 60 +
                ExtractSecond('END_TIME'),
                output_field=FloatField()
            ),
            adjusted_start_seconds=Case(
                When(start_seconds__lt=8.5 * 3600, then=Value(8.5 * 3600)),
                When(start_seconds__gt=19.5 * 3600, then=Value(19.5 * 3600)),
                default=F('start_seconds'),
                output_field=FloatField()
            ),
            adjusted_end_seconds=Case(
                When(end_seconds__lt=8.5 * 3600, then=Value(8.5 * 3600)),
                When(end_seconds__gt=19.5 * 3600, then=Value(19.5 * 3600)),
                default=F('end_seconds'),
                output_field=FloatField()
            ),
            duration_hours=Case(
                When(
                    Q(end_seconds__lte=8.5 * 3600) | Q(start_seconds__gte=19.5 * 3600),
                    then=Value(0)
                ),
                default=ExpressionWrapper(
                    (F('adjusted_end_seconds') - F('adjusted_start_seconds')) / 3600,
                    output_field=FloatField()
                ),
                output_field=FloatField()
            )
        ).filter(duration_hours__gt=0)

        # Filter out break times
        logs = logs.exclude(
            Q(start_seconds__gte=10.5 * 3600, end_seconds__lte=10.6667 * 3600) |
            Q(start_seconds__gte=13.3333 * 3600, end_seconds__lte=14 * 3600) |
            Q(start_seconds__gte=16.3333 * 3600, end_seconds__lte=16.5 * 3600)
        )

        # Calculate metrics
        total_working_days = logs.values('DATE').distinct().count()
        total_available_hours = total_working_days * 10

        mode_hours = logs.values('MODE').annotate(
            total_hours=Sum('duration_hours')
        )

        total_production_hours = sum(
            mode['total_hours'] for mode in mode_hours if mode['MODE'] == 1
        )
        total_non_production_hours = total_available_hours - total_production_hours

        production_percentage = (total_production_hours / total_available_hours * 100) if total_available_hours > 0 else 0
        npt_percentage = 100 - production_percentage

        all_operators_data.append({
            "operatorId": operator.rfid_card_no,
            "operatorName": operator.operator_name,
            "totalProductionHours": round(total_production_hours, 2),
            "totalNonProductionHours": round(total_non_production_hours, 2),
            "productionPercentage": round(production_percentage, 2),
            "nptPercentage": round(npt_percentage, 2),
        })

    return Response(all_operators_data)

from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import MachineLog, Operator

MODES = {
    1: "Sewing",
    2: "Idle",
    3: "No feeding",
    4: "Meeting",
    5: "Maintenance",
}

@api_view(['GET'])
def filter_logs(request):
    LINE_NUMBERer = request.GET.get('LINE_NUMBERer')
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    
    queryset = MachineLog.objects.all()
    
    if LINE_NUMBERer and LINE_NUMBERer.lower() != 'all':
        queryset = queryset.filter(LINE_NUMBER=LINE_NUMBERer)
    
    if from_date:
        queryset = queryset.filter(DATE__gte=from_date)
    
    if to_date:
        queryset = queryset.filter(DATE__lte=to_date)
    
    # Prefetch operator data to optimize queries
    logs = list(queryset)
    operator_ids = set(log.OPERATOR_ID for log in logs if log.OPERATOR_ID != "0")
    operators = Operator.objects.filter(rfid_card_no__in=operator_ids)
    operator_map = {op.rfid_card_no: op.operator_name for op in operators}
    
    data = []
    for log in logs:
        log_data = {
            **log.__dict__,
            'mode_description': MODES.get(log.MODE, 'Unknown mode'),
            'operator_name': operator_map.get(log.OPERATOR_ID, "") if log.OPERATOR_ID != "0" else ""
        }
        # Remove Django internal fields
        log_data.pop('_state', None)
        data.append(log_data)
    
    return Response(data)


@api_view(['GET'])
def filter_logs_by_machine_id(request):
    machine_id = request.GET.get('machine_id')
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    
    queryset = MachineLog.objects.all()
    
    if machine_id and machine_id.lower() != 'all':
        queryset = queryset.filter(MACHINE_ID=machine_id)
    
    if from_date:
        queryset = queryset.filter(DATE__gte=from_date)
    
    if to_date:
        queryset = queryset.filter(DATE__lte=to_date)
    
    # Prefetch operator data to optimize queries
    logs = list(queryset)
    operator_ids = set(log.OPERATOR_ID for log in logs if log.OPERATOR_ID != "0")
    operators = Operator.objects.filter(rfid_card_no__in=operator_ids)
    operator_map = {op.rfid_card_no: op.operator_name for op in operators}
    
    data = []
    for log in logs:
        log_data = {
            **log.__dict__,
            'mode_description': MODES.get(log.MODE, 'Unknown mode'),
            'operator_name': operator_map.get(log.OPERATOR_ID, "") if log.OPERATOR_ID != "0" else ""
        }
        # Remove Django internal fields
        log_data.pop('_state', None)
        data.append(log_data)
    
    return Response(data)

@api_view(['GET'])
def get_LINE_NUMBERers(request):
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    
    if not from_date or not to_date:
        return Response({"error": "Both from_date and to_date are required"}, status=400)
    
    queryset = MachineLog.objects.filter(
        DATE__gte=from_date,
        DATE__lte=to_date
    ).values_list('LINE_NUMBER', flat=True).distinct()
    
    LINE_NUMBERers = sorted(list(queryset))
    return Response({"LINE_NUMBERers": LINE_NUMBERers})

@api_view(['GET'])
def get_machine_ids(request):
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    
    if not from_date or not to_date:
        return Response({"error": "Both from_date and to_date are required"}, status=400)
    
    queryset = MachineLog.objects.filter(
        DATE__gte=from_date,
        DATE__lte=to_date
    ).values_list('MACHINE_ID', flat=True).distinct()
    
    machine_ids = sorted(list(queryset))
    return Response({"machine_ids": machine_ids})







# views.py
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.db.models import Sum, Count, Avg
from datetime import timedelta


MODES = {
    1: "Sewing",
    2: "Idle",
    3: "No feeding",
    4: "Meeting",
    5: "Maintenance",
}

@api_view(['GET'])
def get_operator_ids(request):
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    
    if not from_date or not to_date:
        return Response({"error": "Both from_date and to_date are required"}, status=400)
    
    queryset = MachineLog.objects.filter(
        DATE__gte=from_date,
        DATE__lte=to_date
    ).exclude(OPERATOR_ID="0").values_list('OPERATOR_ID', flat=True).distinct()
    
    operator_ids = sorted(list(queryset))
    return Response({"operator_ids": operator_ids})

@api_view(['GET'])
def operator_report(request, operator_id):
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    
    queryset = MachineLog.objects.filter(OPERATOR_ID=operator_id)
    
    if from_date:
        queryset = queryset.filter(DATE__gte=from_date)
    if to_date:
        queryset = queryset.filter(DATE__lte=to_date)
    
    # Get operator name
    operator_name = ""
    try:
        operator = Operator.objects.get(rfid_card_no=operator_id)
        operator_name = operator.operator_name
    except Operator.DoesNotExist:
        pass
    
    # Calculate totals
    total_hours = queryset.aggregate(
        total_hours=Sum('SKIP_COUNT')
    )['total_hours'] or 0
    
    productive_hours = queryset.filter(MODE=1).aggregate(
        total=Sum('SKIP_COUNT')
    )['total'] or 0
    
    no_feeding_hours = queryset.filter(MODE=3).aggregate(
        total=Sum('SKIP_COUNT')
    )['total'] or 0
    
    meeting_hours = queryset.filter(MODE=4).aggregate(
        total=Sum('SKIP_COUNT')
    )['total'] or 0
    
    maintenance_hours = queryset.filter(MODE=5).aggregate(
        total=Sum('SKIP_COUNT')
    )['total'] or 0
    
    idle_hours = queryset.filter(MODE=2).aggregate(
        total=Sum('SKIP_COUNT')
    )['total'] or 0
    
    total_OPERATION_COUNT = queryset.aggregate(
        total=Sum('OPERATION_COUNT')
    )['total'] or 0
    
    # Prepare daily data
    daily_data = queryset.values('DATE').annotate(
        sewing_hours=Sum('SKIP_COUNT', filter=operator.Q(MODE=1)),
        no_feeding_hours=Sum('SKIP_COUNT', filter=operator.Q(MODE=3)),
        meeting_hours=Sum('SKIP_COUNT', filter=operator.Q(MODE=4)),
        maintenance_hours=Sum('SKIP_COUNT', filter=operator.Q(MODE=5)),
        idle_hours=Sum('SKIP_COUNT', filter=operator.Q(MODE=2)),
        total_hours=Sum('SKIP_COUNT'),
        OPERATION_COUNT=Sum('OPERATION_COUNT'),
        machine_count=Count('MACHINE_ID', distinct=True),
        avg_sewing_speed=Avg('RESERVE')
    ).order_by('DATE')
    
    # Format daily data for table
    table_data = []
    for day in daily_data:
        day_total = day['total_hours'] or 0
        pt_percentage = (day['sewing_hours'] / day_total * 100) if day_total > 0 else 0
        npt_percentage = 100 - pt_percentage
        
        table_data.append({
            "Date": day['DATE'],
            "Sewing Hours (PT)": day['sewing_hours'] or 0,
            "No Feeding Hours": day['no_feeding_hours'] or 0,
            "Meeting Hours": day['meeting_hours'] or 0,
            "Maintenance Hours": day['maintenance_hours'] or 0,
            "Idle Hours": day['idle_hours'] or 0,
            "Total Hours": day_total,
            "Productive Time (PT) %": round(pt_percentage, 2),
            "Non-Productive Time (NPT) %": round(npt_percentage, 2),
            "Sewing Speed": round(day['avg_sewing_speed'] or 0, 2),
            "Stitch Count": day['OPERATION_COUNT'] or 0,
            "Machine Count": day['machine_count'] or 0
        })
    
    # Calculate percentages
    pt_percentage = (productive_hours / total_hours * 100) if total_hours > 0 else 0
    npt_percentage = 100 - pt_percentage
    
    response_data = {
        "operator_id": operator_id,
        "operator_name": operator_name,
        "total_hours": round(total_hours, 2),
        "total_productive_time": {
            "hours": round(productive_hours, 2),
            "percentage": round(pt_percentage, 2)
        },
        "total_non_productive_time": {
            "hours": round(no_feeding_hours + meeting_hours + maintenance_hours + idle_hours, 2),
            "percentage": round(npt_percentage, 2),
            "breakdown": {
                "no_feeding_hours": round(no_feeding_hours, 2),
                "meeting_hours": round(meeting_hours, 2),
                "maintenance_hours": round(maintenance_hours, 2),
                "idle_hours": round(idle_hours, 2)
            }
        },
        "total_OPERATION_COUNT": total_OPERATION_COUNT,
        "table_data": table_data,
        "all_table_data": table_data  # For filtering
    }
    
    return Response(response_data)

@api_view(['GET'])
def all_operators_report(request):
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    
    if not from_date or not to_date:
        return Response({"error": "Both from_date and to_date are required"}, status=400)
    
    # Get all operator data
    operators = MachineLog.objects.filter(
        DATE__gte=from_date,
        DATE__lte=to_date
    ).exclude(OPERATOR_ID="0").values('OPERATOR_ID').distinct()
    
    all_operators_report = []
    
    for operator in operators:
        operator_id = operator['OPERATOR_ID']
        operator_data = MachineLog.objects.filter(
            OPERATOR_ID=operator_id,
            DATE__gte=from_date,
            DATE__lte=to_date
        )
        
        # Get operator name
        operator_name = ""
        try:
            operator_obj = Operator.objects.get(rfid_card_no=operator_id)
            operator_name = operator_obj.operator_name
        except Operator.DoesNotExist:
            pass
        
        # Calculate totals
        total_hours = operator_data.aggregate(
            total_hours=Sum('SKIP_COUNT')
        )['total_hours'] or 0
        
        productive_hours = operator_data.filter(MODE=1).aggregate(
            total=Sum('SKIP_COUNT')
        )['total'] or 0
        
        pt_percentage = (productive_hours / total_hours * 100) if total_hours > 0 else 0
        
        all_operators_report.append({
            "operator_id": operator_id,
            "operator_name": operator_name,
            "total_hours": round(total_hours, 2),
            "productive_hours": round(productive_hours, 2),
            "productive_percentage": round(pt_percentage, 2),
            "OPERATION_COUNT": operator_data.aggregate(
                total=Sum('OPERATION_COUNT')
            )['total'] or 0,
            "machine_count": operator_data.values('MACHINE_ID').distinct().count()
        })
    
    return Response({"allOperatorsReport": all_operators_report})


from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import MachineLog
from .serializers import MachineLogSerializer

@api_view(['GET'])
def get_consolidated_logs(request):
    """
    View to retrieve machine logs with optional date filtering.
    """
    from_date = request.query_params.get('from_date')
    to_date = request.query_params.get('to_date')
    
    logs = MachineLog.objects.all()
    
    if from_date:
        logs = logs.filter(DATE__gte=from_date)
    if to_date:
        logs = logs.filter(DATE__lte=to_date)
    
    logs = logs.order_by('-DATE')[:10000]
    
    serialized_logs = MachineLogSerializer(logs, many=True).data

    # Add indexing (1, 2, 3...)
    for idx, log in enumerate(serialized_logs, start=1):
        log['index'] = idx

    return Response(serialized_logs)








