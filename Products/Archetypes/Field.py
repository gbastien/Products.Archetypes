from __future__ import nested_scopes
from AccessControl import ClassSecurityInfo, getSecurityManager
from Acquisition import aq_base
from types import ListType, TupleType, ClassType, FileType
from UserDict import UserDict
from Products.CMFCore.utils import getToolByName
from Products.CMFCore  import CMFCorePermissions
from Globals import InitializeClass
from Widget import *
from utils import capitalize, DisplayList
from debug import log, log_exc
from ZPublisher.HTTPRequest import FileUpload
from BaseUnit import BaseUnit
from types import StringType
from Storage import AttributeStorage, MetadataStorage, ObjectManagedStorage, \
     ReadOnlyStorage
from DateTime import DateTime
from Layer import DefaultLayerContainer
from interfaces.field import IField, IObjectField
from interfaces.layer import ILayerContainer, ILayerRuntime, ILayer
from interfaces.storage import IStorage
from interfaces.base import IBaseUnit
from exceptions import ObjectFieldException, TextFieldException, FileFieldException
from Products.validation import validation
from config import TOOL_NAME


#For Backcompat and re-export
from Schema import FieldList, MetadataFieldList

class Field(DefaultLayerContainer):
    __implements__ = (IField, ILayerContainer)
    
    security  = ClassSecurityInfo()
    security.declareObjectPublic()
    security.setDefaultAccess("allow")

    _properties = {
        'required' : 0,
        'default' : None,
        'vocabulary' : (),
        'enforceVocabulary' : 0,
        'multiValued' : 0,
        'searchable' : 0,
        'isMetadata' : 0,

        'accessor' : None,
        'mutator' : None,
        'mode' : 'rw',

        'read_permission' : CMFCorePermissions.View,
        'write_permission' : CMFCorePermissions.ModifyPortalContent,

        'storage' : AttributeStorage(),
        'form_info' : None,

        'generateMode' : 'veVc',
        'force' : '',
        'type' : None,
        'widget': StringWidget,
        'validators' : (),
        'index' : None, # "KeywordIndex" "<type>|schema"
        'schemata' : 'default',
        }

    def __init__(self, name, **kwargs):
        DefaultLayerContainer.__init__(self)
        self.__dict__.update(self._properties)
        self.__dict__.update(kwargs)
        self.name = name

        self._widgetLayer()
        self._validationLayer()
        
        self.registerLayer('storage', self.storage)

    def copy(self):
        return self.__class__(**self.__dict__)
    
    def __repr__(self):
        return "<Field %s(%s:%s)>" %(self.name, self.type, self.mode)

    def _widgetLayer(self):
        if hasattr(self, 'widget') and type(self.widget) == ClassType:
            self.widget = self.widget()

    def _validationLayer(self):
        # resolve that each validator is in the service
        # we could replace strings with class refs and keep
        # things impl the ivalidator in the list
        # XXX this is not compat with aq_ things like scripts with
        # __call__
        if type(self.validators) not in [type(()), type([])]:
            self.validators = (self.validators,)
            
        for v in self.validators:
            if not validation.validatorFor(v):
                log("WARNING: no validator %s for %s" % (v,
                self.name))

    def validate(self, value):
        for v in self.validators:
            res = validation.validate(v, value)
            if res != 1:
                return res
            return None

    def Vocabulary(self, content_instance=None):
        value = self.vocabulary
        if not isinstance(value, DisplayList):
            if content_instance is not None and type(value) is StringType:
                method = getattr(content_instance, self.vocabulary, None)
                if method and callable(method):
                    value = method()
                    
            # Post process value into a DisplayList, templates will use
            # this interface
            sample = value[:1]
            if isinstance(sample, DisplayList):
                #Do nothing, the bomb is already set up
                pass
            elif type(sample) == type(()):
                #Assume we have ( (value, display), ...)
                #and if not ('', '', '', ...)
                if len(sample) != 2:
                    value = zip(value, value)
                value = DisplayList(value)
            elif len(sample) and type(sample[0]) == type(''):
                value = DisplayList(zip(value, value))
            else:
                log("Unhandled type in Vocab")
                log(value)

        return value

    def checkPermission(self, mode, instance):
        if mode in ('w', 'write', 'edit', 'set'):
            perm = self.write_permission
        elif mode in ('r', 'read', 'view', 'get'):
            perm = self.read_permission
        else:
            return None
        return getSecurityManager().checkPermission( perm, instance )

    security.declarePublic('getStorageName')
    def getStorageName(self):
        return self.storage.getName()

    security.declarePublic('getWidgetName')
    def getWidgetName(self):
        return self.widget.getName() 

class ObjectField(Field):
    """Base Class for Field objects that fundamentaly deal with raw
    data. This layer implements the interface to IStorage and other
    Field Types should subclass this to delegate through the storage
    layer. 
    """
    __implements__ = (IObjectField, ILayerContainer)

    _properties = Field._properties.copy()
    _properties.update({
        'type' : 'object',
        'default_content_type' : 'application/octet',
        })

    def get(self, instance, **kwargs):
        try:
            kwargs['field'] = self
            return self.storage.get(self.name, instance, **kwargs)
        except AttributeError: # happens if new Atts are added and not yet stored in the instance
            if not kwargs.get('_initializing_', 0):
                self.set(instance,self.default,_initializing_=1,**kwargs)
            return self.default
        
    def set(self, instance, value, **kwargs):
        kwargs['field'] = self
        self.storage.set(self.name, instance, value, **kwargs)

    def unset(self, instance, **kwargs):
        kwargs['field'] = self
        self.storage.unset(self.name, instance, **kwargs)

    def setStorage(self, instance, storage):
        if not IStorage.isImplementedBy(storage):
            raise ObjectFieldException, "Not a valid Storage method"
        value = self.get(instance)
        self.unset(instance)
        self.storage = storage
        if hasattr(self.storage, 'initalizeInstance'):
            self.storage.initalizeInstance(instance)
        self.set(instance, value)

    def getStorage(self):
        return self.storage

class StringField(ObjectField):
    """A string field"""
    _properties = Field._properties.copy()
    _properties.update({
        'type' : 'string',
        'default': '',
        'default_content_type' : 'text/plain',
        })

class MetadataField(ObjectField):
    """Metadata fields have special storage and explictly no markup as
    requirements.
    """
    __implements__ = ObjectField.__implements__

    _properties = Field._properties.copy()
    _properties.update({
        'type' : 'metadata',
        'isMetadata' : 1,
        'generateMode' : 'mVc',
        'mode' : 'rw',
        'storage' : MetadataStorage(),
        })


class FileField(StringField):
    """Something that may be a file, but is not an image and doesn't want text format conversion"""
    __implements__ = ObjectField.__implements__

    _properties = StringField._properties.copy()
    _properties.update({
        'type' : 'file',
        'default' : '',
        'primary' : 0,
        })
                       
    def _process_input(self, value, default=None, mime_type='text/plain', **kwargs):
        # We also need to handle the case where there is a baseUnit
        # for this field containing a valid set of data that would
        # not be reuploaded in a subsequent edit, this is basically
        # migrated from the old BaseObject.set method
        if type(value) is StringType:
            return value, mime_type
        elif ((isinstance(value, FileUpload) and value.filename != '') or
              (isinstance(value, FileType) and value.name != '')):
            return value.read(), mime_type
        raise TextFieldException('Value is not File or String')

    def set(self, instance, value, **kwargs):
        if not kwargs.has_key('mime_type'):
            kwargs['mime_type'] = self.default_content_type
            
        value, mime_type = self._process_input(value,
                                               default=self.default, \
                                               **kwargs)
        # FIXME: ugly hack
        try:
            types_d = instance._FileField_types
            instance._p_changed
        except AttributeError:
            types_d = {}
            instance._FileField_types = types_d
        types_d[self.name] = mime_type
        ObjectField.set(self, instance, value, **kwargs)

        #Invoke the default Transforms, hey, its policy
        #Note that we stash the product of transforms on
        #bu.transforms and BU deals with that
        #tt = getToolByName(self, "transformation_tool")
        #tt.runChains(MUTATION,
        #             bu.getRaw(),
        #             bu.transforms)
        

class TextField(ObjectField):
    """Base Class for Field objects that rely on some type of
    transformation"""
    __implements__ = ObjectField.__implements__

    _properties = Field._properties.copy()
    _properties.update({
        'type' : 'text',
        'default' : '',
        'default_content_type' : 'text/plain',
        'default_output_type'  : 'text/plain',
        'allowable_content_types' : ('text/plain',),
        'primary' : 0,
        })
                       
    def defaultView(self):
        return self.default_output_type
    
    def _process_input(self, value, default=None, mime_type='text/plain', **kwargs):
        # We also need to handle the case where there is a baseUnit
        # for this field containing a valid set of data that would
        # not be reuploaded in a subsequent edit, this is basically
        # migrated from the old BaseObject.set method
        if type(value) != StringType:
            if ((isinstance(value, FileUpload) and value.filename != '') or
                (isinstance(value, FileType) and value.name != '')):
                #OK, its a file, is it empty?
                value.seek(-1, 2)
                size = value.tell()
                value.seek(0)
                if size == 0:
                    # This new file has no length, so we keep
                    # the orig
                    return default
                return value, mime_type

            elif IBaseUnit.isImplementedBy(value):
                return value, getattr(aq_base(value), 'mimetype', mime_type)
        else:
            if value == '':
                return default, mime_type
            return value, mime_type
        raise TextFieldException('Value is not File, String or BaseUnit')

    def set(self, instance, value, **kwargs):
        if not kwargs.has_key('mime_type'):
            kwargs['mime_type'] = self.default_content_type
            
        value, mime_type = self._process_input(value,
                                               default=self.default, \
                                               **kwargs)
        if IBaseUnit.isImplementedBy(value):
            bu = value
        else:
            bu = BaseUnit(self.name, value, mime_type)
        ObjectField.set(self, instance, bu, **kwargs)

        #Invoke the default Transforms, hey, its policy
        #Note that we stash the product of transforms on
        #bu.transforms and BU deals with that
        #tt = getToolByName(self, "transformation_tool")
        #tt.runChains(MUTATION,
        #             bu.getRaw(),
        #             bu.transforms)
        

class DateTimeField(ObjectField):
    __implements__ = ObjectField.__implements__

    _properties = Field._properties.copy()
    _properties.update({
        'type' : 'datetime',
        'widget' : CalendarWidget,
        })

    def set(self, instance, value, **kwargs):
        if not value:
            value = None
        elif not isinstance(value, DateTime):
            try:
                value = DateTime(value)
            except:
                value = None
            
        ObjectField.set(self, instance, value, **kwargs)
        
class LinesField(ObjectField):
    __implements__ = ObjectField.__implements__

    _properties = Field._properties.copy()
    _properties.update({
        'type' : 'lines',
        'default' : [],
        'widget' : LinesWidget,
        })

    def set(self, instance, value, **kwargs):
        if type(value) == type(''):
            value =  value.split('\n')
        value = [v.strip() for v in value if v.strip()]
        value = filter(None, value)
        ObjectField.set(self, instance, value, **kwargs)

class IntegerField(ObjectField):
    __implements__ = ObjectField.__implements__

    _properties = Field._properties.copy()
    _properties.update({
        'type' : 'integer',
        'size' : '10',
        'default' : 0
        })

    def set(self, instance, value, **kwargs):
        try:
            value = int(value)
        except TypeError:
            value = self.default
        
        ObjectField.set(self, instance, value, **kwargs)

class FloatField(ObjectField):
    _properties = Field._properties.copy()
    _properties.update({
        'type' : 'float'
        })

    def set(self, instance, value, **kwargs):
        try:
            value = float(value)
        except TypeError:
            value = None
        
        ObjectField.set(self, instance, value, **kwargs)

class FixedPointField(ObjectField):
    __implements__ = ObjectField.__implements__

    _properties = Field._properties.copy()
    _properties.update({
        'type' : 'fixedpoint',
        'precision' : 2,
        'default' : '0.0',
        'widget' : DecimalWidget,
        'validators' : ('isDecimal'),
        })

    def _to_tuple(self, value):
        value = value.split('.') # FIXME: i18n?
        if len(value) < 2:
            value = (int(value[0]), 0)
        else:
            fra = value[1][:self.precision]
            fra += '0' * (self.precision - len(fra))
            value = (int(value[0]), int(fra))
        return value

    def set(self, instance, value, **kwargs):
        value = self._to_tuple(value)
        ObjectField.set(self, instance, value, **kwargs)

    def get(self, instance, **kwargs):
        template = '%%d.%%0%dd' % self.precision
        value = ObjectField.get(self, instance, **kwargs)
        __traceback_info__ = (template, value)
        if value is None: return self.default
        if type(value) in [StringType]: value = self._to_tuple(value)
        return template % value

class ReferenceField(ObjectField):
    __implements__ = ObjectField.__implements__

    _properties = Field._properties.copy()
    _properties.update({
        'type' : 'reference',
        'default': None,
        'widget' : ReferenceWidget,
        'allowed_types' : (),
        'addable': 0,
        'destination': None,
        })

    def Vocabulary(self, content_instance=None):
        if self.allowed_types:
            catalog = getToolByName(content_instance, 'portal_catalog')
            value = [(obj.UID, str(obj.Title).strip() or str(obj.getId).strip())
                     for obj in catalog(Type=self.allowed_types)]
        else:
            archetype_tool = getToolByName(content_instance, TOOL_NAME)
            value = [(obj.UID, str(obj.Title).strip() or str(obj.getId).strip())
                     for obj in archetype_tool.Content()]
        if not self.required:
            value.insert(0, ('', '<no reference>'))
        return DisplayList(value)

class ComputedField(ObjectField):
    __implements__ = ObjectField.__implements__

    _properties = Field._properties.copy()
    _properties.update({
        'type' : 'computed',
        'expression': None,
        'widget' : ComputedWidget,
        'mode' : 'r',
        'storage': ReadOnlyStorage(),
        })
    
    def set(self, *ignored, **kwargs):
        pass

    def get(self, instance, **kwargs):
        return eval(self.expression, {'context': instance})

class BooleanField(ObjectField):
    __implements__ = ObjectField.__implements__
    _properties = Field._properties.copy()
    _properties.update({
        'type' : 'boolean',
        'default': None,
        'widget' : BooleanWidget,
        })

    def set(self, instance, value, **kwargs):
        
        if not value or value == '0':
            value = None ## False
        else:
            value = 1
        
        ObjectField.set(self, instance, value, **kwargs)
            
class CMFObjectField(ObjectField):
    __implements__ = ObjectField.__implements__
    _properties = Field._properties.copy()
    _properties.update({
        'type' : 'object',
        'portal_type': 'File',
        'default': None,
        'default_mime_type': 'application/octet-stream',
        'widget' : FileWidget(),
        'storage': ObjectManagedStorage(),
        'workflowable': 1,
        })

    def _process_input(self, value, default=None, **kwargs):
        __traceback_info__ = (value, type(value))
        if type(value) != StringType:
            if ((isinstance(value, FileUpload) and value.filename != '') or
                (isinstance(value, FileType) and value.name != '')):
                #OK, its a file, is it empty?
                value.seek(-1, 2)
                size = value.tell()
                value.seek(0)
                if size == 0:
                    # This new file has no length, so we keep
                    # the orig
                    return default
                return value
            if value is None:
                return default
        else:
            if value == '':
                return default
            return value
        
        raise ObjectFieldException('Value is not File or String')

    def get(self, instance, **kwargs):
        try:
            return self.storage.get(self.name, instance, **kwargs)
        except AttributeError:
            # object doesnt exists
            tt = getToolByName(instance, 'portal_types', None)
            if tt is None:
                msg = "Coudln't get portal_types tool from this context"
                raise AttributeError(msg)
            type_name = self.portal_type
            info = tt.getTypeInfo(type_name)
            if info is None:
                raise ValueError('No such content type: %s' % type_name)
            if not hasattr(aq_base(info), 'constructInstance'):
                raise ValueError('Cannot construct content type: %s' % type_name)
            return info.constructInstance(instance, self.name, **kwargs)

    def set(self, instance, value, **kwargs):
        obj = self.get(instance, **kwargs)
        value = self._process_input(value, default=self.default, \
                                    **kwargs)
        if value is None or value == '':
            # do nothing
            return

        obj.edit(file=value)
        # The object should be already stored, so we dont 'set' it,
        # but just change instead.
        # ObjectField.set(self, instance, obj, **kwargs)


# ImageField.py 
# Written in 2003 by Christian Scholz (cs@comlounge.net)
# version: 1.0 (26/02/2002)
from OFS.Image import Image as BaseImage
from cStringIO import StringIO
try:
    import PIL.Image
    has_pil=1
except:
    # no PIL, no scaled versions!
    has_pil=None

class Image(BaseImage):
    def isBinary(self):
        return 1
    

class ImageField(ObjectField):
    """ implements an image attribute. it stores
        it's data in an image sub-object 

        sizes is an dictionary containing the sizes to
        scale the image to. PIL is required for that.

        Format:
        sizes={'mini': (50,50),
               'normal' : (100,100), ... }
        syntax: {'name': (width,height), ... }

        the scaled versions can then be accessed as
        object/<imagename>_<scalename>

        e.g. object/image_mini

        where <imagename> is the fieldname and <scalename>
        is the name from the dictionary

        original_size -- this parameter gives the size in (w,h)
        to which the original image will be scaled. If it's None,
        then no scaling will take place.
        This is important if you don't want to store megabytes of
        imagedata if you only need a max. of 100x100 ;-)

        example:

        ImageField('image',
            original_size=(600,600),
            sizes={ 'mini' : (80,80),
                    'normal' : (200,200),
                    'big' : (300,300),
                    'maxi' : (500,500)})
        
        will create an attribute called "image"
        with the sizes mini, normal, big, maxi as given
        and a original sized image of max 600x600.
        This will be accessible as
        object/image

        and the sizes as

        object/image_mini
        object/image_normal
        object/image_big
        object/image_maxi

        Scaling will only be available if PIL is installed!

        If 'DELETE_IMAGE' will be given as value, then all the images
        will be deleted (None is understood as no-op)
        """

    _properties = Field._properties.copy()
    _properties.update({
        'type' : 'image',
        'default' : '',
        'original_size': (600,600),
        'sizes' : {'thumb':(80,80)},
        'default_content_type' : 'image/gif',
        'allowable_content_types' : ('image/gif','image/jpeg'),
        'widget': ImageWidget,
        'storage': ObjectManagedStorage(),
        })
                       
    default_view = "view"

    def defaultView(self):
        return self.form_info.defaultView() or self.default_view
    
    def set(self, instance, value, **kwargs):
        # do we have to delete the image?
        if value=="DELETE_IMAGE":
            ObjectField.set(self, instance, None, **kwargs)
            return

        if value == '' or type(value) != StringType:
            image = None
            try:
                image = ObjectField.get(self, instance, **kwargs)
            except AttributeError:
                pass

            # just keep stuff if nothing was uploaded
            if not value: return

            # check for file
            if not ((isinstance(value, FileUpload) and value.filename != '') or
                    (isinstance(value, FileType) and value.name != '')):
                return
            
            if image:
                #OK, its a file, is it empty?
                value.seek(-1, 2)
                size = value.tell()
                value.seek(0)
                if size == 0:
                 # This new file has no length, so we keep
                 # the orig
                 return

        ### 
        ### store the original
        ###

        # test for scaling it.
        if self.original_size and has_pil:
            mime_type = kwargs.get('mime_type', 'image/png')
            image = Image(self.name, self.name, value, mime_type)
            data=image.data
            w,h=self.original_size
            imgdata=self.scale(data,w,h)
        else:
            mime_type = kwargs.get('mime_type', 'image/png')
            imgdata=value

        image = Image(self.name, self.name, imgdata, mime_type)
        image.filename = value.filename
        ObjectField.set(self, instance, image, **kwargs)

        # now create the scaled versions
        if not has_pil or not self.sizes: 
            return

        data=str(image.data)
        for n,size in self.sizes.items():
            w,h=size
            id=self.name+"_"+n
            imgdata=self.scale(data,w,h)
            image2=Image(id, self.name, imgdata, 'image/jpeg')
            # manually use storage
            self.storage.set(id,instance,image2)


    def scale(self,data,w,h):
        """ scale image (with material from ImageTag_Hotfix)"""
        #make sure we have valid int's
        keys = {'height':int(w or h), 'width':int(h or w)} 

        original_file=StringIO(data)
        image=PIL.Image.open(original_file)
        image=image.convert('RGB')
        image.thumbnail((keys['width'],keys['height']))
        thumbnail_file=StringIO()
        image.save(thumbnail_file, "JPEG")
        thumbnail_file.seek(0)
        return thumbnail_file.read()

InitializeClass(Field)

__all__ = ('Field', 'ObjectField', 'StringField', 'MetadataField', \
           'FileField', 'TextField', 'DateTimeField', 'LinesField', \
           'IntegerField', 'FloatField', 'FixedPointField', \
           'ReferenceField', 'ComputedField', 'BooleanField', \
           'CMFObjectField', 'ImageField', \
           'FieldList', 'MetadataFieldList', # Those two should go away after 1.0
           )
