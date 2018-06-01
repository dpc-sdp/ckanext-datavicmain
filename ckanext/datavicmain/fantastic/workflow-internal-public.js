  jQuery(document).ready(function() {
    jQuery('#workflow_status').on('change', function() {
        var workflow_status = jQuery(this).val();
        jQuery('#field-private').prop('disabled', (workflow_status == 'published' ? false : true));
    });
  });