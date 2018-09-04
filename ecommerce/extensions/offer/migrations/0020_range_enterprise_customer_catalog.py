# -*- coding: utf-8 -*-
# Generated by Django 1.11.15 on 2018-09-11 17:50
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('offer', '0019_migrate_partner_to_conditional_offers'),
    ]

    operations = [
        migrations.AddField(
            model_name='range',
            name='enterprise_customer_catalog',
            field=models.UUIDField(blank=True, help_text='UUID for an EnterpriseCustomerCatalog from the Enterprise Service.', null=True),
        ),
    ]
