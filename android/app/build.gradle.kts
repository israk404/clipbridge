plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.farhan.clipbridge"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.farhan.clipbridge"
        minSdk = 26
        targetSdk = 35
        versionCode = 2
        versionName = "2.0"
    }

    // One fixed key so every build can be installed over the previous one (no uninstall needed).
    // It lives in the repo — fine for a personal app; keep the repo private.
    signingConfigs {
        create("shared") {
            storeFile = file("clipbridge.keystore")
            storePassword = "clipbridge"
            keyAlias = "clipbridge"
            keyPassword = "clipbridge"
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("shared")
        }
        debug {
            signingConfig = signingConfigs.getByName("shared")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    lint {
        checkReleaseBuilds = false
        abortOnError = false
    }
}

// No third-party libraries: the app only uses Android itself (plus the Kotlin standard library).
