# Generated by Django 2.2.16 on 2020-12-22 19:40

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payment', '0030_auto_20201218_1916'),
    ]

    operations = [
        migrations.AddField(
            model_name='userbillinginfo',
            name='billing_country_iso2',
            field=models.CharField(max_length=2, null=True),
        ),
        migrations.AddField(
            model_name='userbillinginfo',
            name='id_other',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
    ]
