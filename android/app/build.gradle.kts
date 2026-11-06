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
        versionCode = 3
        versionName = "2.0.1"
    }

    // Release signing key comes from the environment (GitHub secrets in CI), never from the repo:
    //   CLIPBRIDGE_KEYSTORE=path/to/release.keystore  CLIPBRIDGE_KEYSTORE_PASSWORD=...
    // Without it, release builds are unsigned (fine for checking that the code compiles).
    val keystorePath = System.getenv("CLIPBRIDGE_KEYSTORE")
    val keystorePassword = System.getenv("CLIPBRIDGE_KEYSTORE_PASSWORD")
    val canSign = !keystorePath.isNullOrEmpty() && !keystorePassword.isNullOrEmpty() && file(keystorePath).exists()

    signingConfigs {
        if (canSign) {
            create("release") {
                storeFile = file(keystorePath!!)
                storePassword = keystorePassword
                keyAlias = System.getenv("CLIPBRIDGE_KEY_ALIAS") ?: "clipbridge"
                keyPassword = keystorePassword
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            if (canSign) signingConfig = signingConfigs.getByName("release")
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
