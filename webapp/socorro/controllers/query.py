from socorro.models import Report, reports_table, Branch, branches_table, Frame, frames_table
from socorro.lib.base import BaseController
from pylons.database import create_engine
from pylons import c, session, request
from pylons.templating import render_response
import formencode
import sqlalchemy
from sqlalchemy import sql, func, select
from sqlalchemy.databases.postgres import PGInterval
import re

class QueryParams(object):
  """An object representing query conditions for end-user searches."""
  def __init__(self):
    self.signature = ''
    self.signature_search = 'signature'
    self.signature_type = 'contains'
    self.date = ''
    self.range_value = 1
    self.range_unit = 'weeks'
    self.products = ()
    self.branches = ()
    self.versions = ()

  def query(self):
    q = Report.query().order_by(sql.desc(reports_table.c.date)).limit(500)
    
    if self.date is None:
      enddate = func.now()
    else:
      enddate = sql.cast(self.date, sqlalchemy.types.DateTime)
    startdate = enddate - sql.cast("%s %s" % (self.range_value, self.range_unit), PGInterval)
    q = q.filter(reports_table.c.date.between(startdate, enddate))

    if self.signature != '':
      if self.signature_type == 'contains':
        pattern = '%' + self.signature.replace('%', '%%') + '%'
        if self.signature_search == 'signature':
          q = q.filter(reports_table.c.signature.like(pattern))
        else:
          q = q.filter(
            sql.exists([1],
                       sql.and_(frames_table.c.signature.like(pattern),
                                frames_table.c.report_id == reports_table.c.id)))
      else:
        if self.signature_search == 'signature':
          q = q.filter(reports_table.c.signature == self.signature)
        else:
          q = q.filter(
            sql.exists([1],
                       sql.and_(frames_table.c.signature == self.signature,
                                frames_table.c.report_id == reports_table.c.id)))

    if len(self.products) > 0:
      q = q.filter(reports_table.c.product.in_(*self.products))
    
    if len(self.branches) > 0:
      q = q.filter(sql.and_(branches_table.c.branch.in_(*self.branches),
                            branches_table.c.product == reports_table.c.product,
                            branches_table.c.version == reports_table.c.version))

    for (product, version) in self.versions:
      q = q.filter(sql.and_(branches_table.c.product == product,
                            branches_table.c.version == version))
    
    return q

  def __str__(self):
    if self.date is None:
      enddate = 'now'
    else:
      enddate = self.date
      
    str = "Results within %s %s of %s" % (self.range_value, self.range_unit, enddate)

    if self.signature != '':
      sigtype = {'exact': 'is exactly',
                 'contains': 'contains'}[self.signature_type]

      sigquery = {'signature': 'the crash signature',
                  'stack': 'one of the top 10 stack frames'}[self.signature_search]
      
      str += ", where %s %s '%s'" % (sigquery, sigtype, self.signature)

    if len(self.products) > 0:
      str += ", and the product is one of %s" % ', '.join(["'%s'" % product for product in self.products])

    if len(self.branches) > 0:
      str += ", and the branch is one of %s" % ', '.join(["'%s'" % branch for branch in self.branches])

    if len(self.versions) > 0:
      str += ", and the version is one of %s" % ', '.join(["'%s %s'" % (product, version) for (product, version) in self.versions])

    str += '.'
    return str

class ProductVersionValidator(formencode.FancyValidator):
  """A custom validator which processes 'product:version' into (product, version)"""

  pattern = re.compile('^([^:]+):(.+)$')

  def _to_python(self, value, state):
    (product, version) = self.pattern.match(value).groups()
    return (product, version)

class QueryParamsValidator(formencode.FancyValidator):
  """A custom formvalidator which processes request.params into a QueryParams
  instance."""

  query_validator = formencode.validators.OneOf(['signature', 'stack'])
  type_validator = formencode.validators.OneOf(['exact', 'contains'])
  datetime_validator = formencode.validators.Regex('^\\d{4}-\\d{2}-\\d{2}( \\d{2}:\\d{2}(:\\d{2})?)?$', strip=True)
  range_unit_validator = formencode.validators.OneOf(['hours', 'days', 'weeks', 'months'])
  string_validator = formencode.validators.String(strip=True)
  version_validator = ProductVersionValidator()

  def _to_python(self, value, state):
    q = QueryParams()
    q.signature = value.get('signature', '')
    q.signature_search = self.query_validator.to_python(value.get('signature_search', 'signature'))
    q.signature_type = self.type_validator.to_python(value.get('signature_type', 'exact'))
    q.date = self.datetime_validator.to_python(value.get('date'), '')
    q.range_value = formencode.validators.Int.to_python(value.get('range_value', '1'))
    q.range_unit = self.range_unit_validator.to_python(value.get('range_unit', 'weeks'))
    q.products = [self.string_validator.to_python(product) for
                  product in value.getall('product')]
    q.branches = [self.string_validator.to_python(branch) for
                  branch in value.getall('branch')]
    q.versions = [self.version_validator.to_python(version) for
                  version in value.getall('version')]
    return q

validator = QueryParamsValidator()

class QueryController(BaseController):
  def query(self):
    if request.params.get('do_query', '') != '':
      c.params = validator.to_python(request.params)
      c.reports = c.params.query().list()
    else:
      c.params = QueryParams()

    c.products = Branch.getProducts()
    c.branches = Branch.getBranches()
    c.prodversions = Branch.getProductVersions()

    return render_response('query_form')
