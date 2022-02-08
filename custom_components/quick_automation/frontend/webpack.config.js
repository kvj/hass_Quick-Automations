export default {
    entry: './index.ts',
    devtool: 'inline-source-map',
    module: {
        rules: [{
            test: /\.ts$/,
            use: 'ts-loader',
            exclude: /node_modules/
        }]
    },
    resolve: {
        extensions: ['.ts', '.js']
    },
    output: {
        filename: './index.js',
        clean: true
    },
    watchOptions: {
        ignored: /node_modules/
    }    
};
