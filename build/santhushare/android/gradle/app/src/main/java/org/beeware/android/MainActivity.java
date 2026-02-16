package org.beeware.android;
import com.example.santhushare.R;
import android.Manifest;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.provider.Settings;
import android.util.Log;
import android.widget.LinearLayout;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;

import com.chaquo.python.Kwarg;
import com.chaquo.python.PyException;
import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import org.json.JSONArray;
import org.json.JSONException;

import java.util.List;

public class MainActivity extends AppCompatActivity {

    private static final String TAG = "MainActivity";
    private static PyObject pythonApp;

    private static final int REQUEST_MANAGE_EXTERNAL_STORAGE = 1;

    @SuppressWarnings("unused")
    public static void setPythonApp(IPythonApp app) {
        pythonApp = PyObject.fromJava(app);
    }

    public static MainActivity singletonThis;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        Log.d(TAG, "onCreate() start");
        setTheme(R.style.AppTheme);
        super.onCreate(savedInstanceState);
        LinearLayout layout = new LinearLayout(this);
        this.setContentView(layout);
        singletonThis = this;

        checkAndRequestPermission();

        Python py;
        if (Python.isStarted()) {
            Log.d(TAG, "Python already started");
            py = Python.getInstance();
        } else {
            Log.d(TAG, "Starting Python");
            AndroidPlatform platform = new AndroidPlatform(this);
            platform.redirectStdioToLogcat();
            Python.start(platform);
            py = Python.getInstance();

            String argvStr = getIntent().getStringExtra("org.beeware.ARGV");
            if (argvStr != null) {
                try {
                    JSONArray argvJson = new JSONArray(argvStr);
                    List<PyObject> sysArgv = py.getModule("sys").get("argv").asList();
                    for (int i = 0; i < argvJson.length(); i++) {
                        sysArgv.add(PyObject.fromJava(argvJson.getString(i)));
                    }
                } catch (JSONException e) {
                    throw new RuntimeException(e);
                }
            }
        }

        Log.d(TAG, "Running main module " + getString(R.string.main_module));
        py.getModule("runpy").callAttr(
                "run_module",
                getString(R.string.main_module),
                new Kwarg("run_name", "__main__"),
                new Kwarg("alter_sys", true)
        );

        userCode("onCreate");
        Log.d(TAG, "onCreate() complete");
    }

private void checkAndRequestPermission() {
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
        if (!Environment.isExternalStorageManager()) {
            Intent intent = new Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION);
            intent.setData(Uri.parse("package:" + getPackageName()));
            if (intent.resolveActivity(getPackageManager()) != null) {
                startActivityForResult(intent, REQUEST_MANAGE_EXTERNAL_STORAGE);
            } else {
                // No activity found to handle the intent, notify the user
                Toast.makeText(this, "Permission setting is not available on this device", Toast.LENGTH_SHORT).show();
            }
        }
    } else {
        // Fallback for older Android versions
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.MANAGE_EXTERNAL_STORAGE)
                != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this,
                    new String[]{Manifest.permission.MANAGE_EXTERNAL_STORAGE},
                    REQUEST_MANAGE_EXTERNAL_STORAGE);
        }
    }
}



    @Override
    public void onRequestPermissionsResult(int requestCode, @NonNull String[] permissions,
                                           @NonNull int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQUEST_MANAGE_EXTERNAL_STORAGE) {
            if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                Log.d(TAG, "External storage permission granted");
                // Proceed with your operations that require this permission
            } else {
                Log.d(TAG, "External storage permission denied");
                // Handle permission denied scenario, possibly show an explanation to the user
            }
        }
    }

    private void userCode(String methodName) {
        if (pythonApp == null) {
            Log.e(TAG, "Python application instance is null");
            return;
        }

        try {
            PyObject method = pythonApp.get(methodName);
            if (method != null) {
                method.call();
            } else {
                Log.e(TAG, "Method " + methodName + " is not callable or does not exist in Python application");
            }
        } catch (PyException e) {
            Log.e(TAG, "Error calling Python method " + methodName + ": " + e.getMessage());
            e.printStackTrace();
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, @Nullable Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQUEST_MANAGE_EXTERNAL_STORAGE) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                if (Environment.isExternalStorageManager()) {
                    Log.d(TAG, "Manage external storage permission granted through settings");
                    // Proceed with operations that require this permission
                } else {
                    Log.d(TAG, "Manage external storage permission denied through settings");
                    // Handle permission denial
                }
            }
        }
    }
}
