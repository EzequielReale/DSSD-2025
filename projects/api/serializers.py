from rest_framework import serializers

class NeedCreateSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=["ECON", "MAT", "MO", "OTRO"])
    description = serializers.CharField(max_length=1000)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    needs_help = serializers.BooleanField(required=False, default=True)

class NeedSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    project_id = serializers.IntegerField()
    type = serializers.CharField()
    description = serializers.CharField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    is_fulfilled = serializers.BooleanField()
    needs_help = serializers.BooleanField()
    commitments = serializers.ListField(child=serializers.DictField(), required=False)

class CommitmentCreateSerializer(serializers.Serializer):
    org_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    quantity = serializers.DecimalField(max_digits=12, decimal_places=2)
    note = serializers.CharField(max_length=1000, required=False, allow_blank=True)

class CommitmentSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    need_id = serializers.IntegerField()
    project_id = serializers.IntegerField()
    org_name = serializers.CharField()
    user = serializers.CharField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=2)
    note = serializers.CharField(allow_blank=True)
    completed = serializers.BooleanField()
    created_at = serializers.DateTimeField()