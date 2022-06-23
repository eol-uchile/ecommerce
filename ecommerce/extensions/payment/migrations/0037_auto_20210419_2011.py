# Generated by Django 2.2.16 on 2021-04-19 20:11

from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('basket', '0013_auto_20200305_1448'),
        ('payment', '0036_auto_20210326_1629'),
    ]

    operations = [
        migrations.AddField(
            model_name='userbillinginfo',
            name='payment_processor',
            field=models.CharField(default='webpay', max_length=10),
        ),
        migrations.CreateModel(
            name='PaypalUSDConversion',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('creation_date', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('clp_to_usd', models.IntegerField(default=750, help_text='Rate used at payment to give the correct price to paypal')),
                ('basket', models.ManyToManyField(blank=True, to='basket.Basket', verbose_name='Basket')),
            ],
            options={
                'ordering': ['creation_date'],
            },
        ),
        migrations.CreateModel(
            name='BoletaUSDConversion',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('creation_date', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('clp_to_usd', models.IntegerField(default=750, help_text='Rate used at boleta emission to get the correct CLP from the USDs')),
                ('boleta', models.ManyToManyField(blank=True, to='payment.BoletaElectronica')),
            ],
            options={
                'ordering': ['creation_date'],
            },
        ),
    ]