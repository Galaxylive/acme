import os
import boto3
import django_filters
import django_tables2 as tables
from django.shortcuts import render, redirect
from django.views import View
from django.contrib import messages
from django.conf import settings
from django.db import connections
from django.core.files.storage import FileSystemStorage
from django.views.generic import TemplateView
from django_filters.views import FilterView
from django_tables2.views import SingleTableMixin
from django_filters.widgets import BooleanWidget
from .forms import FileUploadForm
from .models import Product
from uuid import uuid4



def get_file_name(filename):
    ext = filename.split('.')[-1]
    filename = "%s.%s" % (uuid4(), ext)
    return filename


class FileUploadView(View):
    form_class = FileUploadForm
    template_name = 'core/file_upload.html'

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, context={'form': self.form_class})

    def post(self, request, *args, **kwargs):
        try:
            if settings.DEBUG:
                fs = FileSystemStorage(file_permissions_mode=0o755)
                file_name = fs.save(str(request.FILES['file'].name), request.FILES['file'])
                csv_file_path = os.path.abspath(file_name)
            else:
                session = boto3.Session(
                    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY
                )
                s3 = session.resource('s3')
                key = 'csvs/' + get_file_name(request.FILES['file'].name)
                s3.Bucket(settings.AWS_STORAGE_BUCKET_NAME).put_object(
                    Key=key,
                    Body=request.FILES['file'])
                s3Client = session.client('s3')
                file_url= s3Client.generate_presigned_url('get_object', Params={'Bucket':settings.AWS_STORAGE_BUCKET_NAME, 'Key': key},
                                                ExpiresIn=100)
            conn = connections['default']
            cur = conn.cursor()
            db_table = Product._meta.db_table

            cur.execute("BEGIN")
            if settings.DEBUG:
                cur.execute("COPY"
                            " {}(name,sku,description)".format(Product._meta.db_table) +
                            "FROM %(csv_file_path)s WITH DELIMITER ',' CSV HEADER ;", {'csv_file_path': csv_file_path})
            else:
                cur.execute("COPY"
                            " {}(name,sku,description)".format(Product._meta.db_table) +
                            "FROM PROGRAM 'curl %s' WITH DELIMITER ',' CSV HEADER ;"%file_url)

            cur.execute("DELETE FROM"
                        " {0} a USING {0} b".format(db_table) +
                        " WHERE a.id < b.id AND lower(a.sku) = lower(b.sku);")
            cur.execute("UPDATE {} SET active = random() > 0.5 WHERE  active IS NULL;".format(db_table))
            cur.execute("COMMIT")
        except Exception as e:
            if settings.DEBUG:
                raise (e)
            else:
                messages.error(request, "Could not add products to database.")
                return redirect('core:product-upload')
        messages.success(request, "Successfully added products to database.")
        return redirect('core:home')


class HomeView(TemplateView):
    template_name = 'core/home.html'


class ProductDeleteView(View):
    def get(self, request, *args, **kwargs):
        Product.objects.all().delete()
        messages.success(request, "Successfully deleted all products.")
        return redirect('core:home')


class ProductTable(tables.Table):
    class Meta:
        model = Product
        exclude = ('id',)


class ProductFilter(django_filters.FilterSet):
    active = django_filters.BooleanFilter(field_name='active', widget=BooleanWidget())

    class Meta:
        model = Product
        fields = {
            'sku': ['icontains'],
            'name': ['icontains'],
            'description': ['icontains']
        }


class ProductView(SingleTableMixin, FilterView):
    table_class = ProductTable
    model = Product
    template_name = 'core/product.html'
    filterset_class = ProductFilter
