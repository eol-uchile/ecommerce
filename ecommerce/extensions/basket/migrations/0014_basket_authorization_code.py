# Generated by Django 2.2.23 on 2022-09-29 21:12

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('basket', '0013_auto_20200305_1448'),
    ]

    operations = [
        migrations.AddField(
            model_name='basket',
            name='authorization_code',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
    ]