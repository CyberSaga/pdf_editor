Based on the provided audit dossier, the following concrete bug is introduced in the net diff at `a7e7734`:

### **Bug: `PDFView` Property Proxying Bypasses Lazy Ensure Accessors on `__new__` Doubles**

* **Failure Scenario**: 
  When a test or component instantiates a double of `PDFView` via `__new__` (which bypasses the normal `__init__` constructor and its eager manager instantiation), the manager attributes are left uninitialized. The design introduces "lazy ensure accessors" specifically to construct these managers on demand for such doubles. 
  
  However, the 43 getter/setter property pairs on `PDFView` proxy directly to the manager's attributes (e.g., `self._manager.attribute`) rather than calling the lazy ensure accessors (e.g., `self.ensure_manager().attribute`). As a result, attempting to get or set any of these 43 properties on a `__new__` double will bypass the lazy instantiation logic, resulting in an immediate `AttributeError` due to the missing manager reference.

* **Confidence**: 90%