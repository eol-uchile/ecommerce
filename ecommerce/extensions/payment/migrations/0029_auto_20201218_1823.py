# Generated by Django 2.2.16 on 2020-12-18 18:23

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('payment', '0028_auto_20201210_1808'),
    ]

    operations = [
        migrations.AddField(
            model_name='userbillinginfo',
            name='boleta',
            field=models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.CASCADE, to='payment.BoletaElectronica'),
        ),
        migrations.AddField(
            model_name='userbillinginfo',
            name='id_option',
            field=models.CharField(choices=[('0', 'Rut'), ('1', 'Pasaporte')], default='0', max_length=1),
        ),
        migrations.AlterField(
            model_name='userbillinginfo',
            name='basket',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='basket.Basket', verbose_name='Basket'),
        ),
    ]
