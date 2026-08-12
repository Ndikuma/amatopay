from rest_framework import serializers

class FeeQuoteInputSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=20, decimal_places=2)
    currency = serializers.CharField(max_length=3, default="BIF")
