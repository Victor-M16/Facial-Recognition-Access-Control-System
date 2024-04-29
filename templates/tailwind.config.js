module.exports = {
    plugins: [
        require('flowbite/plugin')
    ],

   darkMode: 'class',
    theme: {
        extend: {
            colors: {
                dark: '#333333',
                
            },
        },
    },

    content: [
        "./node_modules/flowbite/**/*.js"
    ]
};
