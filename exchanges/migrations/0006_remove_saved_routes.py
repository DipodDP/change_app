from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("exchanges", "0005_exchange_made_on"),
    ]

    operations = [
        migrations.DeleteModel(name="RouteStep"),
        migrations.DeleteModel(name="Route"),
    ]
