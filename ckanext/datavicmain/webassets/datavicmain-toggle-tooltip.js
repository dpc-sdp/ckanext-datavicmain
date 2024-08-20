ckan.module('datavicmain-toggle-tooltip', function ($, _) {
    'use strict';

    return {
        options: {},
        initialize: function () {
            document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(
                el => new bootstrap.Tooltip(el)
            );
        }
    }
})
